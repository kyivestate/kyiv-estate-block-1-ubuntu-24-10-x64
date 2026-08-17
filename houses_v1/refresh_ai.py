from __future__ import annotations
import psycopg2
import psycopg2.extras
from parser_v2.services.ai_listing_copy import build_title, clean_source_description, fallback_detailed_description


def main():
    with psycopg2.connect(host='localhost', port=5432, dbname='real_estate', user='admin') as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as read, conn.cursor() as write:
            read.execute("SELECT * FROM houses_listings WHERE status='active' AND (ai_title IS NULL OR ai_description IS NULL OR length(trim(ai_description)) < 100)")
            rows = read.fetchall()
            for row in rows:
                source = clean_source_description(row.get('description'))
                write.execute("UPDATE houses_listings SET ai_title=%s, ai_description=%s, updated_at=NOW() WHERE id=%s",
                              (build_title(row), fallback_detailed_description(row, source), row['id']))
        print(f'ai_refreshed={len(rows)}')


if __name__ == '__main__': main()
