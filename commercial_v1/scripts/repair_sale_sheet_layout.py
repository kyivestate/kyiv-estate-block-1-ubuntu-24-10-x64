"""Safely remove an accidental duplicate-column tail from Commercial Sale.

The production layout is the 56 columns in ``HEADERS`` plus two Block 3 URL
columns (58 total).  A historic
bad write expanded the Sale tab to 770 columns, taking the workbook to the
Google Sheets 10-million-cell limit and preventing normal synchronization.
This tool first creates a Drive copy of the complete workbook, then deletes
only columns after the canonical schema.  It never touches columns A:BF.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, HEADERS, credentials
from parser_v2.services.sheets_lock import SheetsLock


def sale_sheet(service, spreadsheet_id: str) -> dict:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))",
    ).execute()
    for sheet in metadata["sheets"]:
        if sheet["properties"]["title"] == "Продаж":
            return sheet["properties"]
    raise RuntimeError("Commercial workbook has no 'Продаж' tab")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the repair; without it only validates")
    parser.add_argument("--verified-local-backup", type=Path, help="explicit CSV snapshot used only when Drive quota prevents a copy")
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    spreadsheet_id = config["active"]["id"]
    creds = credentials()
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    props = sale_sheet(sheets, spreadsheet_id)
    columns = props["gridProperties"]["columnCount"]
    # Telegraph UA/EN are intentionally appended by Block 3 and are not part
    # of the commercial writer's business-field header list.
    canonical = len(HEADERS) + 2
    result = {"sheet": "Продаж", "rows": props["gridProperties"]["rowCount"], "columns": columns, "canonical_columns": canonical}
    if columns < canonical:
        raise RuntimeError("Sale tab is narrower than the canonical schema; refusing repair")
    if columns == canonical:
        result["status"] = "already_healthy"
        print(json.dumps(result, ensure_ascii=False))
        return
    result["status"] = "repair_required"
    if not args.apply:
        print(json.dumps(result, ensure_ascii=False))
        return
    with SheetsLock("commercial_sale_layout_repair"):
        # Read the grid again only after the writer lock has been acquired.
        props = sale_sheet(sheets, spreadsheet_id)
        columns = props["gridProperties"]["columnCount"]
        if columns <= canonical:
            result["status"] = "already_repaired_by_other_writer"
            print(json.dumps(result, ensure_ascii=False))
            return
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            backup = drive.files().copy(
                fileId=spreadsheet_id,
                body={"name": f"Backup before commercial Sale layout repair — {stamp}"},
                fields="id,name,webViewLink",
            ).execute()
        except Exception as exc:
            # Do not silently perform a destructive repair without a recovery
            # point.  The scheduled encrypted CSV snapshots are acceptable
            # only when the operator explicitly selects one.
            local = args.verified_local_backup
            if not local or not local.is_file() or local.stat().st_size == 0:
                raise RuntimeError("Drive copy failed and no verified local backup was supplied") from exc
            backup = {"local_snapshot": str(local.resolve()), "drive_copy_error": str(exc)}
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteDimension": {"range": {
                "sheetId": props["sheetId"], "dimension": "COLUMNS",
                "startIndex": canonical, "endIndex": columns,
            }}}]},
        ).execute()
        verified = sale_sheet(sheets, spreadsheet_id)
        if verified["gridProperties"]["columnCount"] != canonical:
            raise RuntimeError("Google Sheets did not apply the expected column repair")
    result.update({"status": "repaired", "backup": backup, "deleted_columns": columns - canonical})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
