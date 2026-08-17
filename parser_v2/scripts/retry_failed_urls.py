"""Retry recoverable apartment URLs that previously failed to parse.

This is deliberately separate from the regular discovery pipeline.  It takes
the same process lock as ``pipeline_v2`` and therefore never competes with a
30-minute production run.  Listings that return 404/410 are terminally marked
``gone`` instead of being retried forever; the cleaning service remains the
authority that moves no-longer-live Active rows to Archive.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from parser_v2.config import cfg
from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.logging_setup import get_logger
from parser_v2.services.normalizers import normalize_listing
from parser_v2.services.persistence import (
    get_conn,
    merge_v2_into_active,
    save_normalized_listing,
    save_raw_listing,
)
from parser_v2.services.process_lock import acquire_process_lock

log = get_logger("retry_failed_urls")
APARTMENT_TYPES = {"Квартира"}


def reclassify_terminal_failures(conn: object) -> int:
    """Remove objectively deleted URLs from the recoverable-failure queue."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE parser_v2_raw_listings
               SET parse_status = 'gone', updated_at = NOW()
             WHERE parse_status = 'failed'
               AND error_message ~* '^HTTP (404|410)$'
        """)
        return cur.rowcount


def select_candidates(conn: object, limit: int, max_retries: int) -> list[dict]:
    """Return a balanced batch across both sources and operations.

    The residential v2 table contains apartments only: houses were migrated to
    their own houses_v1 tables.  The explicit URL condition is a second guard
    for Rieltor records.
    """
    per_bucket = max(1, (limit + 3) // 4)
    sql = """
        WITH ranked AS (
          SELECT r.id, r.source, r.operation, r.external_id, r.url,
                 r.retry_count,
                 row_number() OVER (
                   PARTITION BY r.source, r.operation
                   ORDER BY r.retry_count ASC, r.updated_at ASC
                 ) AS bucket_rank
            FROM parser_v2_raw_listings r
           WHERE r.parse_status = 'failed'
             AND r.retry_count < %s
             AND r.url <> ''
             AND (r.source <> 'rieltor' OR r.url LIKE '%%/flats-%%')
        )
        SELECT id, source, operation, external_id, url, retry_count
          FROM ranked
         WHERE bucket_rank <= %s
         ORDER BY retry_count ASC, id ASC
         LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (max_retries, per_bucket, limit))
        columns = [c.name for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def parser_for(source: str, operation: str):
    if source == "olx":
        http = OlxHttpClient(cfg.parser.request_timeout)
        return http, OlxParser(http, operation, 1, APARTMENT_TYPES)
    http = RieltorHttpClient(cfg.parser.request_timeout)
    return http, RieltorParser(http, operation, 1, APARTMENT_TYPES)


def retry_batch(limit: int, max_retries: int, dry_run: bool = False) -> Counter:
    conn = get_conn()
    stats: Counter = Counter()
    clients: dict[tuple[str, str], tuple[object, object]] = {}
    batch_started_at = datetime.now(timezone.utc)
    try:
        terminal = reclassify_terminal_failures(conn)
        if not dry_run:
            conn.commit()
        else:
            conn.rollback()
        stats["terminal_gone"] = terminal
        candidates = select_candidates(conn, limit, max_retries)
        stats["selected"] = len(candidates)
        log.info("terminal gone=%d; retry candidates=%d", terminal, len(candidates))
        for index, row in enumerate(candidates, 1):
            key = (row["source"], row["operation"])
            if key not in clients:
                clients[key] = parser_for(*key)
            _http, parser = clients[key]
            try:
                raw, source_data = parser.fetch_and_parse(row["url"], row["external_id"])


                if raw.http_status in (404, 410):
                    raw.parse_status = "gone"
                    raw.error_message = f"HTTP {raw.http_status}"
                    stats["gone"] += 1
                    if not dry_run:
                        save_raw_listing(conn, raw)
                        conn.commit()
                    continue
                if raw.parse_status != "parsed":
                    stats["still_failed"] += 1
                    if not dry_run:
                        save_raw_listing(conn, raw)
                        conn.commit()
                    continue
                listing = normalize_listing(raw, source_data)
                if not listing.passes_price_filter(cfg.parser.rent_min_uah, cfg.parser.sale_min_usd):
                    raw.parse_status = "filtered"
                    raw.error_message = "price_filter"
                    stats["price_filtered"] += 1
                    if not dry_run:
                        save_raw_listing(conn, raw)
                        conn.commit()
                    continue
                stats["parsed"] += 1
                if not dry_run:
                    raw_id = save_raw_listing(conn, raw)
                    listing.raw_listing_id = raw_id
                    save_normalized_listing(conn, listing)
                    conn.commit()
            except Exception as exc:
                conn.rollback()
                stats["unexpected_error"] += 1
                log.exception("retry %s/%s failed: %s", row["source"], row["external_id"], exc)
            if index % 10 == 0 or index == len(candidates):
                log.info("retry %d/%d: %s", index, len(candidates), dict(stats))
        if stats["parsed"] and not dry_run:


            merged = merge_v2_into_active(conn, since=batch_started_at)
            conn.commit()
            stats["merged"] = merged
        return stats
    finally:
        for http, _parser in clients.values():
            try:
                http.close()
            except Exception:
                pass
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=24, help="maximum URLs per safe batch")
    ap.add_argument("--max-retries", type=int, default=3, help="attempts allowed per URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.limit < 1 or args.max_retries < 1:
        ap.error("--limit and --max-retries must be positive")
    try:
        acquire_process_lock("pipeline_v2")
    except RuntimeError:
        log.info("production apartment pipeline is busy; retry batch skipped")
        return 0
    stats = retry_batch(args.limit, args.max_retries, args.dry_run)
    log.info("retry batch complete: %s", dict(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
