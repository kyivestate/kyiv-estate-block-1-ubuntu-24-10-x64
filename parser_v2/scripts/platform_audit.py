import argparse
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import gspread
import psycopg2
from google.oauth2.service_account import Credentials


ACTIVE_SHEET_ID = "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8"
LIFECYCLE_SHEET_ID = "1B0O2rTAcbfrrMxE1XX-lHDhqi2qt_Mg-U5usql975gg"
CREDS = "/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json"
FIELDS = [
    "rooms", "area", "floor", "floors_total", "district", "city", "street",
    "residential_complex", "metro_station", "photo_url", "description", "ai_title",
    "ai_description",
]


def percent(value, total):
    return round((100 * value / total), 2) if total else 0


def sheets_read(operation, attempts=5):
    error = None
    for attempt in range(attempts):
        try:
            return operation()
        except gspread.exceptions.APIError as exc:
            error = exc
            time.sleep((attempt + 1) * 5)
    raise error


def database_audit():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM active_listings GROUP BY status ORDER BY status")
            statuses = dict(cur.fetchall())
            cur.execute("""SELECT source, operation, count(*)
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                GROUP BY source, operation ORDER BY source, operation""")
            active_by_source = [{"source": source, "operation": operation, "count": count} for source, operation, count in cur.fetchall()]
            cur.execute("""SELECT operation, id::text
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'""")
            active_ids = defaultdict(set)
            for operation, listing_id in cur.fetchall():
                active_ids[operation].add(listing_id)
            coverage_sql = ", ".join(
                f"count(*) filter (where {field} is not null and nullif(trim({field}::text),'') is not null) as {field}"
                for field in FIELDS
            )
            cur.execute(f"""SELECT source, operation, count(*) as total, {coverage_sql}
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                GROUP BY source, operation ORDER BY source, operation""")
            coverage = []
            columns = [item[0] for item in cur.description]
            for values in cur.fetchall():
                record = dict(zip(columns, values))
                total = record.pop("total")
                coverage.append({
                    "source": record.pop("source"),
                    "operation": record.pop("operation"),
                    "total": total,
                    "fields_percent": {field: percent(record[field], total) for field in FIELDS},
                })
            cur.execute("""SELECT count(*) FROM (
                SELECT source, external_id FROM active_listings
                GROUP BY source, external_id HAVING count(*) > 1
            ) duplicates""")
            duplicate_source_external = cur.fetchone()[0]
            cur.execute("""SELECT count(*) FROM (
                SELECT url FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%' AND nullif(trim(url),'') is not null
                GROUP BY url HAVING count(*) > 1
            ) duplicates""")
            duplicate_active_url = cur.fetchone()[0]
            return {
                "statuses": statuses,
                "active_by_source": active_by_source,
                "active_ids": active_ids,
                "coverage": coverage,
                "duplicate_source_external": duplicate_source_external,
                "duplicate_active_url": duplicate_active_url,
            }
    finally:
        conn.close()


def inspect_book(client, sheet_id, include_ids=False, expected_ids=None):
    book = sheets_read(lambda: client.open_by_key(sheet_id))
    report = {"title": book.title, "id": sheet_id, "tabs": []}
    expected_ids = expected_ids or {}
    for worksheet in sheets_read(book.worksheets):
        header = sheets_read(lambda: worksheet.row_values(1))
        tab = {
            "title": worksheet.title,
            "rows_capacity": worksheet.row_count,
            "columns_capacity": worksheet.col_count,
            "header": header,
        }
        if include_ids:
            rows = sheets_read(worksheet.get_all_values)
            try:
                id_index = header.index("ID")
            except ValueError:
                id_index = -1
            ids = [row[id_index].strip() for row in rows[1:] if id_index >= 0 and len(row) > id_index and row[id_index].strip()]
            operation = "rent" if "оренд" in worksheet.title.lower() or "rent" in worksheet.title.lower() else "buy" if "прод" in worksheet.title.lower() or "buy" in worksheet.title.lower() else ""
            db_ids = expected_ids.get(operation, set())
            tab.update({
                "rows_with_id": len(ids),
                "duplicate_ids": sum(count - 1 for count in Counter(ids).values() if count > 1),
                "db_active_ids": len(db_ids),
                "missing_from_sheet": len(db_ids - set(ids)),
                "not_active_in_db": len(set(ids) - db_ids),
            })
        report["tabs"].append(tab)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    db = database_audit()
    credentials = Credentials.from_service_account_file(CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(credentials)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {key: value for key, value in db.items() if key != "active_ids"},
        "active_sheet": inspect_book(client, ACTIVE_SHEET_ID, include_ids=True, expected_ids=db["active_ids"]),
        "lifecycle_sheet": inspect_book(client, LIFECYCLE_SHEET_ID),
    }
    output = args.output or os.path.join("logs", f"platform_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(output, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"AUDIT_REPORT={os.path.abspath(output)}")


if __name__ == "__main__":
    main()
