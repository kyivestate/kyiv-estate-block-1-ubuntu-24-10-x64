"""Read-only quality report for the Section X projection."""
from __future__ import annotations

import json

from contact_coverage_v1.refresh import get_conn


def main() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT source, contact_method, COUNT(*)
              FROM contact_coverage_listings
             WHERE status='active'
             GROUP BY source, contact_method
             ORDER BY source, contact_method
        """)
        report = {'active': [{'source': source, 'contact_method': method, 'records': count} for source, method, count in cur.fetchall()]}
        cur.execute("SELECT count(*) FROM contact_coverage_listings WHERE needs_review")
        report['needs_review'] = cur.fetchone()[0]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
