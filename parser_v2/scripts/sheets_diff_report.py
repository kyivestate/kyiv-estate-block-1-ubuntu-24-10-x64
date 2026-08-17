import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gspread
import psycopg2
import psycopg2.extras
from google.oauth2.service_account import Credentials

from parser_v2.scripts.run_all import HEADERS, SHEET_ID, _cell_matches, row30


CREDS = "/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json"
IGNORED_COLUMNS = {2, 27, 28, 30, 31}
TABS = {"rent": "Оренда", "buy": "Продаж"}


def database_rows():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""SELECT * FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                ORDER BY id""")
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def inspect_tab(worksheet, expected_rows):
    values = worksheet.get_all_values(value_render_option="FORMULA")
    if not values or values[0] != HEADERS:
        raise RuntimeError(f"{worksheet.title}: unexpected schema")
    actual = {row[0].strip(): row for row in values[1:] if row and row[0].strip()}
    mismatches = Counter()
    examples = defaultdict(list)
    missing = []
    for row in expected_rows:
        expected = row30(row)
        existing = actual.get(expected[0])
        if existing is None:
            missing.append(expected[0])
            continue
        for index, expected_value in enumerate(expected):
            if index in IGNORED_COLUMNS:
                continue
            current_value = existing[index] if len(existing) > index else ""
            if not _cell_matches(current_value, expected_value):
                field = HEADERS[index]
                mismatches[field] += 1
                if len(examples[field]) < 10:
                    examples[field].append(expected[0])
    stale = sorted(set(actual) - {str(row["id"]) for row in expected_rows})
    return {
        "sheet_rows": len(actual),
        "database_rows": len(expected_rows),
        "missing_ids": missing[:100],
        "missing_count": len(missing),
        "stale_ids": stale[:100],
        "stale_count": len(stale),
        "field_mismatch_counts": dict(mismatches),
        "examples": dict(examples),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    rows = database_rows()
    by_operation = {operation: [row for row in rows if row["operation"] == operation] for operation in TABS}
    credentials = Credentials.from_service_account_file(CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    book = gspread.authorize(credentials).open_by_key(SHEET_ID)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tabs": {operation: inspect_tab(book.worksheet(tab), by_operation[operation]) for operation, tab in TABS.items()},
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        print(f"SHEETS_DIFF_REPORT={path.resolve()}")


if __name__ == "__main__":
    main()
