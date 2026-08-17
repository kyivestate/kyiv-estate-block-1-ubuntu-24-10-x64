import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
import psycopg2.extras

from parser_v2.services.ai_listing_copy import build_title, clean_source_description, fallback_detailed_description
from parser_v2.services.process_lock import acquire_process_lock

CONTENT_VERSION = 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if args.workers < 1 or args.worker < 0 or args.worker >= args.workers:
        raise SystemExit("invalid worker partition")
    try:
        acquire_process_lock(f"rebuild_ai_content_{args.worker}")
    except RuntimeError:
        print(f"worker={args.worker} already_running")
        return
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        read = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        write = conn.cursor()
        write.execute("""CREATE TABLE IF NOT EXISTS ai_content_rebuilds (
            listing_id BIGINT PRIMARY KEY REFERENCES active_listings(id),
            version INTEGER NOT NULL,
            rebuilt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        conn.commit()
        params = [CONTENT_VERSION, args.workers, args.worker, args.limit]
        read.execute(f"""SELECT id, operation, property_type, rooms, area, district, residential_complex,
            street, metro_station, floor, floors_total, description
            FROM active_listings listing
            LEFT JOIN ai_content_rebuilds rebuilt ON rebuilt.listing_id=listing.id
            WHERE status='active' AND source NOT LIKE 'findly%%'
              AND description IS NOT NULL AND length(trim(description)) >= 40
              AND (rebuilt.version IS NULL OR rebuilt.version < %s)
              AND listing.id %% %s = %s
            ORDER BY listing.id LIMIT %s""", params)
        rows = read.fetchall()
        updated = 0
        for index, row in enumerate(rows, 1):
            source = clean_source_description(row.get("description"))
            if len(source) < 40:
                continue
            write.execute("UPDATE active_listings SET ai_title=%s, ai_description=%s, updated_at=NOW() WHERE id=%s", (build_title(row), fallback_detailed_description(row, source), row["id"]))
            write.execute("""INSERT INTO ai_content_rebuilds (listing_id, version, rebuilt_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (listing_id) DO UPDATE SET version=EXCLUDED.version, rebuilt_at=EXCLUDED.rebuilt_at""",
                (row["id"], CONTENT_VERSION))
            updated += 1
            if index % 100 == 0:
                conn.commit()
                print(f"worker={args.worker} processed={index} updated={updated}", flush=True)
        conn.commit()
        print(f"worker={args.worker} total={len(rows)} updated={updated}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
