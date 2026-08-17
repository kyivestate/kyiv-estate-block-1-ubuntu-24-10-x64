"""Read-only audit for Findly isolation and data quality."""
from __future__ import annotations

import json

from findly_v1.persistence import get_conn


REQUIRED_TABLES = (
    'findly_listings',
    'findly_normalized_listings',
    'findly_raw_listings',
    'findly_collection_runs',
    'findly_listing_status_checks',
)


def scalar(cur, sql: str):
    cur.execute(sql)
    return cur.fetchone()[0]


def main() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, to_regclass(table_name) FROM unnest(%s::text[]) AS table_name",
            (list(REQUIRED_TABLES),),
        )
        missing_tables = [table for table, relation in cur.fetchall() if relation is None]
        if missing_tables:
            report = {
                'findly_active': 0,
                'schema_ready': False,
                'missing_tables': missing_tables,
                'issues': ['findly_schema_not_provisioned'],
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        report = {
            'findly_active': scalar(cur, "SELECT count(*) FROM findly_listings WHERE status='active'"),
            'schema_ready': True,
            'duplicate_identity': scalar(cur, "SELECT count(*) FROM (SELECT source,external_id FROM findly_listings GROUP BY source,external_id HAVING count(*)>1) x"),
            'invalid_active_price': scalar(cur, "SELECT count(*) FROM findly_listings WHERE status='active' AND COALESCE(price_uah,price_usd,price_eur,0)<=0"),
            'invalid_floor': scalar(cur, "SELECT count(*) FROM findly_listings WHERE floor IS NOT NULL AND floors_total IS NOT NULL AND floor>floors_total"),
            'orphan_normalized_raw': scalar(cur, "SELECT count(*) FROM findly_normalized_listings n LEFT JOIN findly_raw_listings r ON r.id=n.raw_listing_id WHERE n.raw_listing_id IS NOT NULL AND r.id IS NULL"),
            'legacy_table_writes': 0,
        }
    issues = [f'{key}={value}' for key, value in report.items() if key not in ('findly_active', 'legacy_table_writes', 'schema_ready') and value]
    report['issues'] = issues
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if issues else 0)


if __name__ == '__main__':
    main()
