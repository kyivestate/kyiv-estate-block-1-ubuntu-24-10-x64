import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2

from parser_v2.config import cfg
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.process_lock import acquire_process_lock


DEFAULT_LIMITS = {"olx": 1000, "rieltor": 300}


def ensure_table(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS listing_status_checks (
        listing_id BIGINT PRIMARY KEY REFERENCES active_listings(id),
        checked_at TIMESTAMPTZ NOT NULL,
        http_status INTEGER,
        error_text TEXT,
        missing_count INTEGER NOT NULL DEFAULT 0,
        last_seen_at TIMESTAMPTZ
    )""")
    cursor.execute("ALTER TABLE listing_status_checks ADD COLUMN IF NOT EXISTS missing_count INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE listing_status_checks ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
    cursor.execute("CREATE INDEX IF NOT EXISTS listing_status_checks_checked_at_idx ON listing_status_checks(checked_at)")


def select_rows(cursor, source, limit):
    cursor.execute("""SELECT listing.id, listing.url
        FROM active_listings listing
        LEFT JOIN listing_status_checks checked ON checked.listing_id=listing.id
        WHERE listing.status='active' AND listing.source=%s AND listing.url LIKE 'http%%'
        ORDER BY checked.checked_at NULLS FIRST, listing.id
        LIMIT %s""", (source, limit))
    return cursor.fetchall()


def save_result(cursor, listing_id, status, error):
    checked_at = datetime.now(timezone.utc)
    cursor.execute("""INSERT INTO listing_status_checks
        (listing_id, checked_at, http_status, error_text, missing_count, last_seen_at)
        VALUES (%s, %s, %s, %s,
            CASE WHEN %s IN (404, 410) THEN 1 ELSE 0 END,
            CASE WHEN %s BETWEEN 200 AND 399 THEN %s ELSE NULL END)
        ON CONFLICT (listing_id) DO UPDATE SET
            checked_at=EXCLUDED.checked_at,
            http_status=EXCLUDED.http_status,
            error_text=EXCLUDED.error_text,
            missing_count=CASE
                WHEN EXCLUDED.http_status IN (404, 410) THEN listing_status_checks.missing_count + 1
                WHEN EXCLUDED.http_status BETWEEN 200 AND 399 THEN 0
                ELSE listing_status_checks.missing_count
            END,
            last_seen_at=CASE
                WHEN EXCLUDED.http_status BETWEEN 200 AND 399 THEN EXCLUDED.checked_at
                ELSE listing_status_checks.last_seen_at
            END
        RETURNING missing_count""",
        (listing_id, checked_at, status, error[:500] if error else None, status, status, checked_at))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def check_source(conn, source, limit):
    client = OlxHttpClient(cfg.parser.request_timeout) if source == "olx" else RieltorHttpClient(cfg.parser.request_timeout)
    if source == "rieltor":
        client._min_delay = 5.0
    checked = 0
    inactive = 0
    failures = 0
    confirmed = 0
    try:
        with conn.cursor() as cursor:
            for listing_id, url in select_rows(cursor, source, limit):
                status = None
                error = ""
                try:
                    status, _ = client.get(url)
                except Exception as exc:
                    error = str(exc)
                    failures += 1
                missing_count = save_result(cursor, listing_id, status, error)
                if status in (404, 410) and missing_count >= 2:
                    cursor.execute("""UPDATE active_listings
                        SET status='inactive', updated_at=NOW(),
                            comments=COALESCE(NULLIF(comments,''), %s)
                        WHERE id=%s AND status='active'""", (f"source_http_{status}_confirmed", listing_id))
                    inactive += cursor.rowcount
                    confirmed += 1
                conn.commit()
                checked += 1
    finally:
        client.close()
    return checked, inactive, failures, confirmed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--olx-limit", type=int, default=DEFAULT_LIMITS["olx"])
    parser.add_argument("--rieltor-limit", type=int, default=DEFAULT_LIMITS["rieltor"])
    args = parser.parse_args()
    limits = {"olx": max(args.olx_limit, 0), "rieltor": max(args.rieltor_limit, 0)}
    try:
        process_lock = acquire_process_lock("check_listing_statuses")
    except RuntimeError:
        print("status_check=already_running")
        return
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        with conn.cursor() as cursor:
            ensure_table(cursor)
        conn.commit()
        result = {source: check_source(conn, source, limits[source]) for source in ("olx", "rieltor")}
    finally:
        conn.close()
    print(" ".join(
        f"{source}:checked={checked},inactive={inactive},failures={failures},confirmed={confirmed}"
        for source, (checked, inactive, failures, confirmed) in result.items()
    ))


if __name__ == "__main__":
    main()
