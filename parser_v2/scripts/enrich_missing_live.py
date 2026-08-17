import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
import psycopg2.extras

from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.scripts.backfill_from_raw import needs_backfill, updates_for, values_from_source
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.process_lock import acquire_process_lock


DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin"}


def valid_updates(row, updates):
    for field in ("rooms", "floor", "floors_total"):
        if field in updates:
            try:
                value = int(updates[field])
            except (TypeError, ValueError):
                updates.pop(field, None)
                continue
            if value < 1 or value > (30 if field == "rooms" else 120):
                updates.pop(field, None)
    if "area" in updates:
        try:
            value = float(updates["area"])
            if not 10 <= value <= 1000:
                updates.pop("area", None)
        except (TypeError, ValueError):
            updates.pop("area", None)
    floor = updates.get("floor", row.get("floor"))
    floors_total = updates.get("floors_total", row.get("floors_total"))
    try:
        if floor is not None and floors_total is not None and int(floor) > int(floors_total):
            updates.pop("floor", None)
            updates.pop("floors_total", None)
    except (TypeError, ValueError):
        updates.pop("floor", None)
        updates.pop("floors_total", None)
    return updates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("olx", "rieltor"), required=True)
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=250)
    args = parser.parse_args()
    if args.workers < 1 or args.worker < 0 or args.worker >= args.workers or args.limit < 1:
        raise SystemExit("invalid worker partition")
    try:
        acquire_process_lock(f"live_enrichment_{args.source}_{args.worker}")
    except RuntimeError:
        print(f"source={args.source} worker={args.worker} already_running")
        return
    conn = psycopg2.connect(**DB)
    http = OlxHttpClient(timeout=25) if args.source == "olx" else RieltorHttpClient(timeout=25)
    if args.source == "olx":
        http._min_delay = 0.45
    else:
        http._min_delay = 5.0
    stats = {"rows": 0, "updated": 0, "fields": 0, "failed": 0, "missing": 0}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as read, conn.cursor() as write:
            write.execute("""CREATE TABLE IF NOT EXISTS listing_live_enrichment_attempts (
                listing_id BIGINT PRIMARY KEY REFERENCES active_listings(id),
                checked_at TIMESTAMPTZ NOT NULL
            )""")
            conn.commit()
            read.execute("""SELECT listing.id, listing.source, listing.operation, listing.property_type, listing.url,
                listing.title, listing.description, listing.rooms, listing.area, listing.floor, listing.floors_total,
                listing.district, listing.street, listing.residential_complex, listing.metro_station,
                listing.agent_type, listing.agent_name, listing.agent_phone, listing.commission,
                listing.photo_url, listing.photos
                FROM active_listings listing
                LEFT JOIN listing_live_enrichment_attempts attempt ON attempt.listing_id=listing.id
                WHERE listing.status='active' AND listing.source=%s AND listing.url LIKE 'http%%'
                  AND (attempt.checked_at IS NULL OR attempt.checked_at < NOW() - INTERVAL '7 days')
                  AND (listing.rooms IS NULL OR listing.area IS NULL OR listing.floor IS NULL
                    OR listing.floors_total IS NULL OR listing.district IS NULL OR listing.district=''
                    OR listing.street IS NULL OR listing.street='' OR listing.metro_station IS NULL OR listing.metro_station=''
                    OR listing.photo_url IS NULL OR listing.photo_url='' OR listing.description IS NULL
                    OR length(trim(listing.description)) < 40)
                  AND listing.id %% %s = %s
                ORDER BY listing.updated_at ASC NULLS FIRST, listing.id
                LIMIT %s""", (args.source, args.workers, args.worker, args.limit))
            rows = read.fetchall()
            for row in rows:
                stats["rows"] += 1
                checked = False
                try:
                    status, html = http.get(row["url"])
                    checked = True
                    if status == 200:
                        source_parser = OlxParser(http, row["operation"]) if args.source == "olx" else RieltorParser(http, row["operation"])
                        extracted = source_parser._extract(html, row["url"])
                        updates = valid_updates(row, updates_for(row, values_from_source(row, extracted))) if needs_backfill(row) else {}
                        if updates:
                            assignments = ", ".join(f"{field}=%s" for field in updates)
                            write.execute(f"UPDATE active_listings SET {assignments}, updated_at=NOW() WHERE id=%s", [*updates.values(), row["id"]])
                            stats["updated"] += 1
                            stats["fields"] += len(updates)
                    elif status in (404, 410):
                        stats["missing"] += 1
                    else:
                        stats["failed"] += 1
                except Exception:
                    stats["failed"] += 1
                if checked:
                    write.execute("""INSERT INTO listing_live_enrichment_attempts (listing_id, checked_at)
                        VALUES (%s, NOW()) ON CONFLICT (listing_id) DO UPDATE SET checked_at=EXCLUDED.checked_at""", (row["id"],))
                if stats["rows"] % 50 == 0:
                    conn.commit()
            conn.commit()
    finally:
        http.close()
        conn.close()
    print(" ".join(f"{key}={value}" for key, value in stats.items()))


if __name__ == "__main__":
    main()
