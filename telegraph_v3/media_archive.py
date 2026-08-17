#!/usr/bin/env python3
"""Durable, local, content-addressed archive for listing photos.

The archive is deliberately independent of a source URL: OLX/Rieltor may
remove an image tomorrow, while a verified local copy remains available for
the public media server and for a later Telegraph refresh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import requests

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = Path(os.getenv("MEDIA_ARCHIVE_ROOT", "/Users/admin/KyivEstateMedia"))
MIN_FREE_BYTES = int(os.getenv("MEDIA_ARCHIVE_MIN_FREE_GB", "50")) * 1024**3
CATALOGS = {"apartments": "active_listings", "houses": "houses_listings", "commercial": "commercial_listings"}
ACCEPTED = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


def db():
    # Postgres.app can require an interactive permission dialog for TCP
    # localhost connections launched by launchd.  The local Unix socket is
    # authenticated as the current macOS user and keeps this unattended job
    # independent of that dialog.
    return psycopg2.connect(host="/tmp", port=5432, dbname="real_estate", user="admin")


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS block3")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS block3.media_archive (
                source_sha256 TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                file_sha256 TEXT,
                storage_key TEXT,
                mime_type TEXT,
                byte_size BIGINT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                archived_at TIMESTAMPTZ,
                checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS media_archive_status_idx ON block3.media_archive(status, checked_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS media_archive_source_archived_idx ON block3.media_archive(source_url) WHERE status='archived'")
        # Do not issue `ADD COLUMN IF NOT EXISTS` on every five-minute job.
        # PostgreSQL still queues an ACCESS EXCLUSIVE lock for that statement;
        # an archive batch intentionally keeps its read transaction open while
        # downloading, so an audit could otherwise wait behind it and then
        # stall every later reader.  Migrate only when the column is actually
        # absent.
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='block3'
              AND table_name='media_archive'
              AND column_name='retry_after'
        """)
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE block3.media_archive ADD COLUMN retry_after TIMESTAMPTZ")
    conn.commit()


def source_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def source_urls(conn, catalogs: list[str], limit: int) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    with conn.cursor() as cur:
        for catalog in catalogs:
            cur.execute(f"""
                WITH candidate_urls AS (
                    SELECT
                        value.url AS url,
                        min(CASE
                            -- Telegraph pages that are already waiting for
                            -- these photos must win over the background
                            -- crawl.  Otherwise lexical URL ordering can
                            -- leave the publisher retrying the same few
                            -- listings while their images sit far back in a
                            -- 100k-photo queue.
                            WHEN publication.status IN ('pending', 'retry') THEN 0
                            WHEN publication.listing_id IS NULL THEN 1
                            ELSE 2
                        END) AS priority,
                        max(listing.updated_at) AS source_updated_at
                    FROM {CATALOGS[catalog]} listing
                    LEFT JOIN block3.publications publication
                      ON publication.catalog = %s
                     AND publication.listing_id = listing.id
                    CROSS JOIN LATERAL unnest(
                        coalesce(listing.photos, ARRAY[]::text[]) || ARRAY[listing.photo_url]
                    ) AS value(url)
                    WHERE listing.status='active' AND value.url LIKE 'https://%%'
                    GROUP BY value.url
                )
                SELECT candidate.url
                FROM candidate_urls candidate
                ORDER BY candidate.priority, candidate.source_updated_at NULLS LAST, candidate.url
            """, (catalog,))
            for (value,) in cur.fetchall():
                url = str(value or "").strip()
                # This crawl can contain more than 100k images.  Membership
                # in a list made selection O(n²), spending minutes of CPU
                # before the first download.  Preserve deterministic order
                # while deduplicating in O(1).
                if url.startswith("https://") and url not in seen:
                    seen.add(url)
                    found.append(url)
    if not found:
        return []
    hashes = [source_hash(url) for url in found]
    with conn.cursor() as cur:
        cur.execute("SELECT source_sha256,status,retry_after FROM block3.media_archive WHERE source_sha256 = ANY(%s)", (hashes,))
        state = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    now = time.time()
    def ready(url: str) -> bool:
        status, retry_after = state.get(source_hash(url), ("pending", None))
        if status in {"archived", "gone", "invalid"}:
            return False
        return retry_after is None or retry_after.timestamp() <= now
    return [url for url in found if ready(url)][:limit]


def free_space_ok() -> bool:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(ARCHIVE_ROOT).free >= MIN_FREE_BYTES


def download_one(url: str) -> dict[str, Any]:
    digest = source_hash(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KyivEstateMediaArchive/1.0)", "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    try:
        # A slow/dead image CDN must not monopolise one of the fixed worker
        # slots during the accelerated backfill.  Retryable sources are
        # revisited later; responsive images keep the durable queue moving.
        response = requests.get(url, headers=headers, timeout=(5, 15))
        response.raise_for_status()
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        payload = response.content
        if mime not in ACCEPTED or len(payload) < 128:
            raise RuntimeError(f"unsupported image response: {mime or 'unknown'}")
        file_digest = hashlib.sha256(payload).hexdigest()
        key = f"files/{file_digest[:2]}/{file_digest}{ACCEPTED[mime]}"
        path = ARCHIVE_ROOT / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Multiple archive runs may encounter the same source URL.  A
            # shared `*.part` name lets one worker rename another worker's
            # temporary file and creates a false retry.  Use a unique file in
            # the same directory so the final replace stays atomic.
            descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                temporary.replace(path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        return {"url": url, "source_hash": digest, "file_hash": file_digest, "key": key, "mime": mime, "bytes": len(payload)}
    except Exception as exc:
        return {"url": url, "source_hash": digest, "error": str(exc)[:1200]}


def record(conn, result: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        if result.get("error"):
            error = result["error"]
            if "404 Client Error" in error or "410 Client Error" in error:
                status, retry_after = "gone", None
            elif "422 Client Error" in error or "unsupported image response" in error:
                status, retry_after = "invalid", None
            else:
                status = "retry"
            cur.execute("""
                INSERT INTO block3.media_archive(source_sha256,source_url,status,attempts,last_error,retry_after,checked_at)
                VALUES(%s,%s,%s,1,%s,CASE WHEN %s='retry' THEN now() + interval '6 hours' ELSE NULL END,now())
                ON CONFLICT(source_sha256) DO UPDATE SET status=EXCLUDED.status,attempts=block3.media_archive.attempts+1,last_error=EXCLUDED.last_error,retry_after=EXCLUDED.retry_after,checked_at=now()
            """, (result["source_hash"], result["url"], status, error, status))
        else:
            cur.execute("""
                INSERT INTO block3.media_archive(source_sha256,source_url,file_sha256,storage_key,mime_type,byte_size,status,attempts,last_error,archived_at,checked_at)
                VALUES(%s,%s,%s,%s,%s,%s,'archived',1,NULL,now(),now())
                ON CONFLICT(source_sha256) DO UPDATE SET file_sha256=EXCLUDED.file_sha256,storage_key=EXCLUDED.storage_key,mime_type=EXCLUDED.mime_type,byte_size=EXCLUDED.byte_size,status='archived',attempts=block3.media_archive.attempts+1,last_error=NULL,archived_at=now(),checked_at=now()
            """, (result["source_hash"], result["url"], result["file_hash"], result["key"], result["mime"], result["bytes"]))
    conn.commit()


def run(limit: int, catalogs: list[str], workers: int) -> dict[str, int]:
    if not free_space_ok():
        raise RuntimeError(f"archive paused: less than {MIN_FREE_BYTES // 1024**3} GB free")
    with db() as conn:
        ensure_schema(conn)
        urls = source_urls(conn, catalogs, limit)
        summary = {"selected": len(urls), "archived": 0, "retry": 0, "bytes": 0}
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as pool:
            futures = [pool.submit(download_one, url) for url in urls]
            for future in as_completed(futures):
                result = future.result()
                record(conn, result)
                if result.get("error"):
                    summary["retry"] += 1
                else:
                    summary["archived"] += 1
                    summary["bytes"] += int(result["bytes"])
        return summary


def audit() -> dict[str, Any]:
    with db() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT status,count(*),coalesce(sum(byte_size),0) FROM block3.media_archive GROUP BY status ORDER BY status")
            rows = [
                {"status": status, "count": int(count), "bytes": int(byte_size or 0)}
                for status, count, byte_size in cur.fetchall()
            ]
    return {"root": str(ARCHIVE_ROOT), "free_gb": round(shutil.disk_usage(ARCHIVE_ROOT).free / 1024**3, 1), "minimum_free_gb": MIN_FREE_BYTES // 1024**3, "states": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--catalog", action="append", choices=sorted(CATALOGS))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    if args.audit:
        print(json.dumps(audit(), ensure_ascii=False))
        return
    print(json.dumps(run(max(1, args.limit), args.catalog or list(CATALOGS), args.workers), ensure_ascii=False))


if __name__ == "__main__":
    main()
