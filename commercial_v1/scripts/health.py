from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection


def scalar(cursor, query: str) -> int:
    cursor.execute(query)
    return int(cursor.fetchone()[0])


def main() -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status, count(*) FROM commercial_listings GROUP BY status ORDER BY status")
        statuses = {status: count for status, count in cursor.fetchall()}
        cursor.execute("SELECT source, operation, count(*) FROM commercial_listings WHERE status='active' GROUP BY source, operation ORDER BY source, operation")
        by_source = [{"source": source, "operation": operation, "count": count} for source, operation, count in cursor.fetchall()]
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statuses": statuses,
            "active_by_source": by_source,
            "duplicate_source_external": scalar(cursor, "SELECT count(*) FROM (SELECT source, external_id FROM commercial_listings GROUP BY source, external_id HAVING count(*) > 1) duplicates"),
            "active_outside_kyiv_region": scalar(cursor, "SELECT count(*) FROM commercial_listings WHERE status='active' AND 'outside_kyiv_region'=ANY(validation_errors)"),
            "negative_prices": scalar(cursor, "SELECT count(*) FROM commercial_listings WHERE price_amount < 0 OR price_per_m2 < 0"),
            "invalid_floor": scalar(cursor, "SELECT count(*) FROM commercial_listings WHERE floor IS NOT NULL AND floors_total IS NOT NULL AND floor > floors_total"),
            "latest_parsed_at": None,
        }
        cursor.execute("SELECT max(parsed_at) FROM commercial_listings")
        latest = cursor.fetchone()[0]
        report["latest_parsed_at"] = latest.isoformat() if latest else None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
