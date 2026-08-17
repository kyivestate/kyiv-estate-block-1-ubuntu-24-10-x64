import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
import psycopg2.extras

from parser_v2.services.ai_listing_copy import build_title, clean_source_description, fallback_detailed_description
from parser_v2.services.process_lock import acquire_process_lock

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ai_fast")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        acquire_process_lock(f"generate_ai_fast_{args.worker}")
    except RuntimeError:
        log.info("AI worker %d already running", args.worker)
        return
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        read = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        write = conn.cursor()
        read.execute("""SELECT id, operation, property_type, rooms, area, district,
            residential_complex, street, metro_station, floor, floors_total, description
            FROM active_listings
            WHERE status='active' AND source NOT LIKE 'findly%%'
              AND description IS NOT NULL AND LENGTH(TRIM(description)) > 40
              AND (ai_title IS NULL OR LENGTH(TRIM(ai_title)) < 18
                   OR LOWER(TRIM(ai_title)) IN ('опис','добре','ок','none','null','title','назва')
                   OR ai_title ~ '^#?[0-9]+'
                   OR ai_description IS NULL OR LENGTH(TRIM(ai_description)) < 100
                   OR LOWER(TRIM(ai_description)) IN ('опис','добре','ок','none','null','description')
                   OR ai_description ~ '^#?[0-9]+'
                   OR lower(ai_description) ~ '(комісі|ріелтор|риелтор|брокер|агент|власник|контакт|телефон|дзвон|звон|пишіть|звертайтеся|не турбувати)')
              AND id %% %s = %s
            ORDER BY data_completeness DESC NULLS LAST""", (args.workers, args.worker))
        rows = read.fetchall()
        log.info("W%d: %d rows", args.worker, len(rows))
        started = time.time()
        for index, row in enumerate(rows, 1):
            description = fallback_detailed_description(row, clean_source_description(row.get("description")))
            write.execute("UPDATE active_listings SET ai_title=%s, ai_description=%s, updated_at=NOW() WHERE id=%s", (build_title(row), description, row["id"]))
            conn.commit()
            if index % 25 == 0:
                rate = index / max(time.time() - started, 0.001)
                log.info("W%d [%d/%d] %.1f rows/s", args.worker, index, len(rows), rate)
        log.info("W%d DONE %d", args.worker, len(rows))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
