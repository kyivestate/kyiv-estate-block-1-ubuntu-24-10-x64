from __future__ import annotations

import json
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, HEADERS, SCOPES
from commercial_v1.scripts.sync_commercial_sheets import column_name


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    book = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)).open_by_key(config["active"]["id"])
    target_tabs = ("Оренда", "Продаж", "Історія — Оренда", "Історія — Продаж")
    for title in target_tabs:
        worksheet = book.worksheet(title)
        worksheet.batch_clear([f"A:{column_name(max(len(HEADERS), 52))}"])
        worksheet.update(range_name=f"A1:{column_name(len(HEADERS))}1", values=[HEADERS], value_input_option="USER_ENTERED")
        book.batch_update({"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": worksheet.id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {"updateDimensionProperties": {"range": {"sheetId": worksheet.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
        ]})
    print(f"migrated_tabs={len(target_tabs)} columns={len(HEADERS)}")


if __name__ == "__main__":
    main()
