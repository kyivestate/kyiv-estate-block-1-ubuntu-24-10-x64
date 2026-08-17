from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import ACTIVE_TITLE, CONFIG_PATH, CREDS, HEADERS, LIFECYCLE_TITLE, SCOPES, TABS


def sheet_id(value: str) -> str:
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value.strip()


def format_book(book, title: str, tabs: tuple[str, str]) -> None:
    book.update_title(title)
    try:
        rent = book.worksheet(tabs[0])
    except gspread.WorksheetNotFound:
        default = book.sheet1
        if not default.row_values(1):
            rent = default
            rent.update_title(tabs[0])
        else:
            rent = book.add_worksheet(title=tabs[0], rows=1000, cols=len(HEADERS))
    try:
        sale = book.worksheet(tabs[1])
    except gspread.WorksheetNotFound:
        sale = book.add_worksheet(title=tabs[1], rows=1000, cols=len(HEADERS))
    for worksheet in (rent, sale):
        current = worksheet.row_values(1)
        if current and current != HEADERS:
            raise RuntimeError(f"{title}/{worksheet.title}: first row is not empty and has an unexpected schema")
        if not current:
            worksheet.update(range_name="A1:BC1", values=[HEADERS], value_input_option="USER_ENTERED")
        book.batch_update({"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": worksheet.id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {"updateDimensionProperties": {"range": {"sheetId": worksheet.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
        ]})


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach user-owned Google Sheets to commercial pipeline")
    parser.add_argument("--active")
    parser.add_argument("--lifecycle")
    parser.add_argument("--workbook")
    args = parser.parse_args()
    if not args.workbook and not (args.active and args.lifecycle):
        parser.error("provide --workbook or both --active and --lifecycle")
    if args.workbook and (args.active or args.lifecycle):
        parser.error("--workbook cannot be combined with --active or --lifecycle")
    if CONFIG_PATH.exists():
        raise RuntimeError(f"{CONFIG_PATH} already exists; refusing to replace configured sheets")
    client = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
    if args.workbook:
        workbook_id = sheet_id(args.workbook)
        workbook = client.open_by_key(workbook_id)
        active_tabs = ("Оренда", "Продаж")
        format_book(workbook, ACTIVE_TITLE, active_tabs)
        expected_tabs = set(active_tabs)
        for worksheet in workbook.worksheets():
            if worksheet.title not in expected_tabs and not worksheet.row_values(1):
                workbook.del_worksheet(worksheet)
        result = {
            "active": {"id": workbook_id, "url": f"https://docs.google.com/spreadsheets/d/{workbook_id}/edit", "title": ACTIVE_TITLE, "tabs": {"rent": active_tabs[0], "buy": active_tabs[1]}},
            "headers": HEADERS,
        }
    else:
        active_id, lifecycle_id = sheet_id(args.active), sheet_id(args.lifecycle)
        active, lifecycle = client.open_by_key(active_id), client.open_by_key(lifecycle_id)
        format_book(active, ACTIVE_TITLE, TABS)
        format_book(lifecycle, LIFECYCLE_TITLE, TABS)
        result = {
            "active": {"id": active_id, "url": f"https://docs.google.com/spreadsheets/d/{active_id}/edit", "title": ACTIVE_TITLE, "tabs": {"rent": TABS[0], "buy": TABS[1]}},
            "lifecycle": {"id": lifecycle_id, "url": f"https://docs.google.com/spreadsheets/d/{lifecycle_id}/edit", "title": LIFECYCLE_TITLE, "tabs": {"rent": TABS[0], "buy": TABS[1]}},
            "headers": HEADERS,
        }
    CONFIG_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
