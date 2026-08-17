import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
from psycopg2.errors import DeadlockDetected
import psycopg2.extras

from parser_v2.services.ai_listing_copy import build_title, clean_source_description, fallback_detailed_description
from parser_v2.services.process_lock import acquire_process_lock


def main():
    try:
        acquire_process_lock("fill_new_listings")
    except RuntimeError:
        print("fill_new_listings=already_running")
        return
    for attempt in range(3):
        conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
        try:
            read = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            write = conn.cursor()
            read.execute("""SELECT id, operation, property_type, rooms, area, district,
            residential_complex, street, metro_station, floor, floors_total, description,
            ai_title, ai_description
            FROM active_listings
            WHERE status='active' AND source NOT LIKE 'findly%%'
              AND (ai_title IS NULL OR LENGTH(TRIM(ai_title)) < 18
                   OR ai_description IS NULL OR LENGTH(TRIM(ai_description)) < 100)
            ORDER BY parsed_at DESC NULLS LAST, id DESC""")
            rows = read.fetchall()
            updated = 0
            for row in rows:
                source_description = clean_source_description(row.get("description"))
                # ``fallback_detailed_description`` also safely renders listings
                # with only structured source fields; do not leave those cards
                # without AI copy merely because a portal omitted prose.
                values = {}
                if not row.get("ai_title") or len(row["ai_title"].strip()) < 18:
                    values["ai_title"] = build_title(row)
                if not row.get("ai_description") or len(row["ai_description"].strip()) < 100:
                    values["ai_description"] = fallback_detailed_description(row, source_description)
                if values:
                    fields = ", ".join(f"{name}=%s" for name in values)
                    write.execute(f"UPDATE active_listings SET {fields}, updated_at=NOW() WHERE id=%s", [*values.values(), row["id"]])
                    updated += 1
                if updated and updated % 500 == 0:
                    conn.commit()
            conn.commit()
            print(f"filled={updated}")
            return
        except DeadlockDetected:
            conn.rollback()
            if attempt == 2:
                raise
            print(f"fill_deadlock_retry={attempt + 1}")
            time.sleep(2 ** attempt)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
