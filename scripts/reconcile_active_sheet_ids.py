#!/usr/bin/env python3
"""Fast ID-level reconciliation of the three Active Google workbooks.

The full syncs own field updates.  This guard owns only set equality: clear
stale/duplicate/orphan rows and write records that are missing from column A.
It never rewrites an existing active row, so user comments cannot be shifted or
overwritten while a parser is producing a live delta.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import gspread
import psycopg2
import psycopg2.extras
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, SCOPES, HEADERS as COMMERCIAL_HEADERS
from commercial_v1.scripts.sync_commercial_sheets import record as commercial_record, rows_for as commercial_rows
from houses_v1.sync_sheets import HEADERS as HOUSE_HEADERS, SHEET_ID as HOUSE_SHEET_ID, record_values as house_record
from manual_v1 import active_records, capture_sheet_notes
from parser_v2.scripts.run_all import HEADERS as APARTMENT_HEADERS, SHEET_ID as APARTMENT_SHEET_ID, row30 as apartment_record
from parser_v2.services.sheets_lock import SheetsLock

DB = dict(host="localhost", port=5432, dbname="real_estate", user="admin")
TABS = {"rent": "Оренда", "buy": "Продаж"}


def retry(action, attempts: int = 6):
    error = None
    for attempt in range(attempts):
        try:
            return action()
        except Exception as exc:
            error = exc
            transient = any(code in str(exc) for code in (
                "429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED",
                "timed out", "Timeout", "Connection",
            ))
            if not transient or attempt + 1 == attempts:
                raise
            time.sleep(min(30, 2 ** attempt))
    raise error


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def rows_for(catalog: str, operation: str) -> list[dict]:
    if catalog == "commercial":
        return commercial_rows(operation)
    table = "active_listings" if catalog == "apartments" else "houses_listings"
    source_filter = " AND source NOT LIKE 'findly%%'" if catalog == "apartments" else ""
    with psycopg2.connect(**DB) as connection:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                f"SELECT * FROM {table} WHERE status='active' AND operation=%s{source_filter} ORDER BY updated_at DESC",
                (operation,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        rows.extend(active_records(connection, catalog, operation))
        return rows


def row_values(catalog: str, row: dict) -> list[str]:
    if catalog == "apartments":
        return apartment_record(row)
    if catalog == "houses":
        return house_record(row)
    return commercial_record(row)


def clear_rows(worksheet, positions: list[int], width: int) -> int:
    ranges: list[list[int]] = []
    for position in sorted(set(positions), reverse=True):
        if ranges and position == ranges[-1][0] - 1:
            ranges[-1][0] = position
        else:
            ranges.append([position, position])
    right = column_name(width)
    for offset in range(0, len(ranges), 25):
        clear_ranges = [f"A{start}:{right}{end}" for start, end in ranges[offset:offset + 25]]
        retry(lambda clear_ranges=clear_ranges: worksheet.batch_clear(clear_ranges))
        time.sleep(0.5)
    return len(set(positions))


def delete_rows(worksheet, positions: list[int]) -> int:
    """Delete rows bottom-to-top so active apartment/house tabs never gain gaps."""
    ranges: list[list[int]] = []
    for position in sorted(set(positions), reverse=True):
        if ranges and position == ranges[-1][0] - 1:
            ranges[-1][0] = position
        else:
            ranges.append([position, position])
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": worksheet.id, "dimension": "ROWS",
            "startIndex": start - 1, "endIndex": end,
        }}}
        for start, end in ranges
    ]
    for offset in range(0, len(requests), 100):
        retry(lambda batch=requests[offset:offset + 100]: worksheet.spreadsheet.batch_update({"requests": batch}))
    return len(set(positions))


def write_rows(worksheet, start_row: int, rows: list[list[str]], width: int) -> int:
    right = column_name(width)
    for offset in range(0, len(rows), 25):
        batch = rows[offset:offset + 25]
        first = start_row + offset
        last = first + len(batch) - 1
        retry(lambda batch=batch, first=first, last=last: worksheet.update(
            range_name=f"A{first}:{right}{last}", values=batch, value_input_option="USER_ENTERED",
        ))
        time.sleep(0.5)
    return len(rows)


def reconcile_tab(connection, worksheet, catalog: str, operation: str, business_width: int, approved_width: int, comment_index: int) -> dict:
    if worksheet.col_count > approved_width:
        retry(lambda: worksheet.resize(cols=approved_width))



    comment_column = column_name(comment_index + 1)
    id_values, comment_values = retry(lambda: worksheet.batch_get(
        ["A:A", f"{comment_column}:{comment_column}"], value_render_option="FORMULA",
    ))
    id_column = [str(row[0]).strip() if row else "" for row in id_values]
    comments = [str(row[0]).strip() if row else "" for row in comment_values]
    note_rows = [[""] * (comment_index + 1) for _ in range(max(len(id_column), len(comments)))]
    for index, identifier in enumerate(id_column):
        note_rows[index][0] = identifier
    for index, comment in enumerate(comments):
        note_rows[index][comment_index] = comment
    capture_sheet_notes(connection, catalog, note_rows, 0, comment_index)
    by_id: dict[str, int] = {}
    duplicates: list[int] = []
    for position, identifier in enumerate(id_column[1:], 2):
        if not identifier:
            continue
        if identifier in by_id:
            duplicates.append(position)
        else:
            by_id[identifier] = position

    expected_rows = rows_for(catalog, operation)
    expected = {str(row["id"]): row_values(catalog, row) for row in expected_rows}
    stale = [position for identifier, position in by_id.items() if identifier not in expected]



    cleared = (
        clear_rows(worksheet, stale + duplicates, approved_width)
        if catalog == "commercial"
        else delete_rows(worksheet, stale + duplicates)
    )

    present = set(by_id) & set(expected)
    missing = [values for identifier, values in expected.items() if identifier not in present]
    after_ids = retry(lambda: worksheet.col_values(1))
    required = len(after_ids) + len(missing) + 10
    if worksheet.row_count < required:
        retry(lambda: worksheet.resize(rows=required))
    written = write_rows(worksheet, len(after_ids) + 1, missing, business_width)
    return {
        "db": len(expected), "present_before": len(by_id), "written": written,
        "cleared": cleared, "duplicates": len(duplicates), "orphans": 0,
    }


def main() -> int:
    commercial = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    credentials = Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)
    client = gspread.authorize(credentials)
    client.http_client.timeout = (20, 120)
    books = {
        "apartments": (retry(lambda: client.open_by_key(APARTMENT_SHEET_ID)), APARTMENT_HEADERS, len(APARTMENT_HEADERS)),
        "houses": (retry(lambda: client.open_by_key(HOUSE_SHEET_ID)), HOUSE_HEADERS, len(HOUSE_HEADERS) + 2),
        "commercial": (retry(lambda: client.open_by_key(commercial["active"]["id"])), COMMERCIAL_HEADERS, len(COMMERCIAL_HEADERS) + 2),
    }
    result: dict[str, dict] = {}



    with SheetsLock("reconcile_active_sheet_ids", wait_seconds=1800), psycopg2.connect(**DB) as connection:
        for catalog, (book, headers, approved_width) in books.items():
            result[catalog] = {}
            for operation, default_tab in TABS.items():
                tab = commercial["active"]["tabs"][operation] if catalog == "commercial" else default_tab
                result[catalog][operation] = reconcile_tab(
                    connection, retry(lambda tab=tab: book.worksheet(tab)), catalog, operation, len(headers), approved_width,
                    headers.index("Коментарі"),
                )
                print(json.dumps({catalog: {operation: result[catalog][operation]}}, ensure_ascii=False), flush=True)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
