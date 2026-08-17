#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, SCOPES
from parser_v2.scripts.run_all import SHEET_ID as APARTMENTS_SHEET_ID
from parser_v2.services.sheets_lock import SheetsLock

TABS = ("Оренда", "Продаж")


def retry(action, attempts: int = 6):
    for attempt in range(attempts):
        try:
            return action()
        except Exception as error:
            retryable = any(code in str(error) for code in (
                "429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "Timeout", "timed out", "Connection",
            ))
            if not retryable or attempt + 1 == attempts:
                raise
            time.sleep(min(30, 2 ** attempt))


def sheet_ids() -> dict[str, str]:
    load_dotenv(ROOT / "houses_v1" / ".env")
    commercial = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["active"]["id"]
    houses = os.environ.get("HOUSES_ACTIVE_SHEET_ID", "").strip()
    if not houses:
        raise RuntimeError("HOUSES_ACTIVE_SHEET_ID is not configured")
    return {"apartments": APARTMENTS_SHEET_ID, "houses": houses, "commercial": commercial}


def empty_rows(worksheet) -> list[int]:
    values = retry(lambda: worksheet.get_all_values(value_render_option="FORMULA"))
    return [row_number for row_number, row in enumerate(values[1:], start=2) if not any(str(value).strip() for value in row)]


def delete_rows(worksheet, rows: list[int]) -> int:
    ranges: list[list[int]] = []
    for row in sorted(set(rows), reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": worksheet.id,
            "dimension": "ROWS",
            "startIndex": start - 1,
            "endIndex": end,
        }}}
        for start, end in ranges
    ]
    for index in range(0, len(requests), 100):
        retry(lambda batch=requests[index:index + 100]: worksheet.spreadsheet.batch_update({"requests": batch}))
    return len(set(rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete fully empty rows from Active Google Sheets.")
    parser.add_argument("--dry-run", action="store_true", help="Report empty rows without deleting them.")
    parser.add_argument("--catalog", choices=("apartments", "houses", "commercial"), action="append")
    args = parser.parse_args()

    credentials = Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)
    client = gspread.authorize(credentials)
    selected = args.catalog or tuple(sheet_ids())
    result: dict[str, dict[str, int]] = {}

    with SheetsLock("remove_empty_active_sheet_rows", wait_seconds=900):
        for catalog in selected:
            book = client.open_by_key(sheet_ids()[catalog])
            result[catalog] = {}
            for tab in TABS:
                rows = empty_rows(book.worksheet(tab))
                result[catalog][tab] = len(rows) if args.dry_run else delete_rows(book.worksheet(tab), rows)

    print(json.dumps({"dry_run": args.dry_run, "empty_rows": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
