"""Build Section X from existing Block 1 catalogs without network requests.

Only phones that are already stored as public source fields are copied. OLX
numbers that merely look like phone numbers in a listing text are marked for
manual review and are never copied into ``contact_phone`` automatically.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from contact_coverage_v1.config import cfg


PHONE_PATTERN = r"(\+?38[\s()\-]*0\d(?:[\s()\-]*\d){8}|0\d(?:[\s()\-]*\d){8})"


def get_conn():
    return psycopg2.connect(
        host=cfg.db_host, port=cfg.db_port, dbname=cfg.db_name,
        user=cfg.db_user, password=cfg.db_password or None,
    )


def source_rows(cur) -> list[dict[str, Any]]:


    cur.execute(
        """
        SELECT 'apartments' AS catalog, id AS listing_id, lower(source) AS source,
               external_id, operation, status, url AS source_url,
               COALESCE(agent_phone, '') AS contact_phone,
               CASE WHEN NULLIF(btrim(COALESCE(agent_phone, '')), '') IS NULL THEN 0 ELSE 1 END AS phone_count,
               (COALESCE(title, '') || ' ' || COALESCE(description, '')) ~ %s AS text_phone_candidate
          FROM active_listings
        UNION ALL
        SELECT 'houses', id, lower(source), external_id, operation, status, url,
               COALESCE(agent_phone, ''),
               CASE WHEN NULLIF(btrim(COALESCE(agent_phone, '')), '') IS NULL THEN 0 ELSE 1 END,
               (COALESCE(title, '') || ' ' || COALESCE(description, '')) ~ %s
          FROM houses_listings
        UNION ALL
        SELECT 'commercial', id, lower(source), external_id, operation, status, url,
               array_to_string(COALESCE(phones, ARRAY[]::text[]), ' '),
               cardinality(COALESCE(phones, ARRAY[]::text[])),
               (COALESCE(title, '') || ' ' || COALESCE(description, '')) ~ %s
          FROM commercial_listings
        """,
        (PHONE_PATTERN, PHONE_PATTERN, PHONE_PATTERN),
    )
    return [dict(row) for row in cur.fetchall()]


def project(row: dict[str, Any]) -> dict[str, Any]:
    phone = str(row['contact_phone']).strip()
    if phone:
        return {**row, 'contact_method': 'public_phone', 'phone_origin': 'public_listing_field', 'needs_review': False}
    if row['source'] == 'olx' and row['text_phone_candidate']:
        return {**row, 'contact_method': 'source_link', 'contact_phone': '', 'phone_count': 0,
                'phone_origin': 'public_text_candidate', 'needs_review': True}
    return {**row, 'contact_method': 'source_link', 'contact_phone': '', 'phone_count': 0,
            'phone_origin': '', 'needs_review': False}


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {'records': len(rows), 'by_source': {}}
    for row in rows:
        bucket = result['by_source'].setdefault(row['source'], {'records': 0, 'public_phone': 0, 'source_link': 0, 'needs_review': 0})
        bucket['records'] += 1
        bucket[row['contact_method']] += 1
        bucket['needs_review'] += int(row['needs_review'])
    return result


def apply(cur, rows: list[dict[str, Any]]) -> None:
    values = [(
        row['catalog'], row['listing_id'], row['source'], row['external_id'], row['operation'], row['status'], row['source_url'],
        row['contact_method'], row['contact_phone'], row['phone_count'], row['phone_origin'], row['needs_review'],
    ) for row in rows]
    execute_values(cur, """
        INSERT INTO contact_coverage_listings
          (catalog, listing_id, source, external_id, operation, status, source_url, contact_method, contact_phone, phone_count, phone_origin, needs_review)
        VALUES %s
        ON CONFLICT (catalog, source, external_id) DO UPDATE SET
          listing_id=EXCLUDED.listing_id, operation=EXCLUDED.operation, status=EXCLUDED.status, source_url=EXCLUDED.source_url,
          contact_method=EXCLUDED.contact_method, contact_phone=EXCLUDED.contact_phone, phone_count=EXCLUDED.phone_count,
          phone_origin=EXCLUDED.phone_origin, needs_review=EXCLUDED.needs_review, last_seen_at=NOW(), updated_at=NOW()
    """, values, page_size=500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write only contact_coverage_listings; default is read-only')
    args = parser.parse_args()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        rows = [project(row) for row in source_rows(cur)]
        output = report(rows)
        output['mode'] = 'apply' if args.apply else 'dry-run'
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if args.apply:
            apply(cur, rows)
            conn.commit()


if __name__ == '__main__':
    main()
