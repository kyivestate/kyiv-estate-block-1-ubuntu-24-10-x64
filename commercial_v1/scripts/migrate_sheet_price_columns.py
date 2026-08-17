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


OLD_HEADERS = HEADERS[:11] + [
    "Ціна, грн", "Ціна, $", "Ціна, €", "Період ціни", "Ціна за м²", "Період ціни за м²",
] + HEADERS[19:]


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    book = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)).open_by_key(config["active"]["id"])
    migrated = []
    for worksheet in book.worksheets():
        header = worksheet.row_values(1)
        if header == HEADERS:
            continue
        if header != OLD_HEADERS:
            raise RuntimeError(f"{worksheet.title}: unexpected schema; refusing to change columns")
        book.batch_update({"requests": [{
            "insertDimension": {"range": {"sheetId": worksheet.id, "dimension": "COLUMNS", "startIndex": 16, "endIndex": 18}, "inheritFromBefore": True}
        }]})
        worksheet.update(range_name="A1:BA1", values=[HEADERS], value_input_option="USER_ENTERED")
        migrated.append(worksheet.title)
    print(json.dumps({"migrated_tabs": migrated, "columns": len(HEADERS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
