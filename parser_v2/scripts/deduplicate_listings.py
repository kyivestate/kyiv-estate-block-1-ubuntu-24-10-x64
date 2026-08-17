import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2

from parser_v2.services.process_lock import acquire_process_lock

def main():
    try:
        process_lock = acquire_process_lock("deduplicate_listings")
    except RuntimeError:
        return
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        with conn.cursor() as cur:
            cur.execute("""WITH ranked AS (
                SELECT id, first_value(id) OVER (PARTITION BY url ORDER BY updated_at DESC NULLS LAST, id DESC) AS keeper
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%' AND nullif(trim(url),'') IS NOT NULL
            )
            UPDATE active_listings a
            SET status='inactive', comments='duplicate_url:' || ranked.keeper::text, updated_at=NOW()
            FROM ranked
            WHERE a.id=ranked.id AND ranked.id<>ranked.keeper""")
            exact = cur.rowcount
            cur.execute("""WITH candidates AS (
                SELECT id, first_value(id) OVER (
                    PARTITION BY operation, lower(regexp_replace(trim(title), '\\s+', ' ', 'g')), coalesce(area,0), coalesce(price_uah,0), regexp_replace(coalesce(agent_phone,''), '\\D', '', 'g')
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                ) AS keeper
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%' AND length(trim(title))>=30 AND coalesce(area,0)>0 AND coalesce(price_uah,0)>0 AND length(regexp_replace(coalesce(agent_phone,''), '\\D', '', 'g'))>=10
            )
            UPDATE active_listings a
            SET status='inactive', comments='duplicate_fingerprint:' || candidates.keeper::text, updated_at=NOW()
            FROM candidates
            WHERE a.id=candidates.id AND candidates.id<>candidates.keeper""")
            fingerprint = cur.rowcount
        conn.commit()
        print(f"exact={exact} fingerprint={fingerprint}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
