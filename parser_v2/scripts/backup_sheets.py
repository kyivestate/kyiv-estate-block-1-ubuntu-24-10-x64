import argparse
import atexit
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gspread
from gspread.exceptions import APIError
from google.auth.exceptions import TransportError
from google.oauth2.service_account import Credentials
from requests.exceptions import RequestException
from gspread.utils import ValueRenderOption
from parser_v2.services.sheets_lock import SheetsLock


CREDS = "/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json"
BOOKS = {
    "apartments": ("1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8", ("Оренда", "Продаж", "Ручне додавання")),
    "houses": ("1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY", ("Оренда", "Продаж", "Ручне додавання")),
}
TAB_NAMES = {"Оренда": "rent", "Продаж": "buy", "Ручне додавання": "manual"}


def retry_google(operation, attempts=6):
    error = None
    for attempt in range(attempts):
        try:
            return operation()
        except (APIError, TransportError, RequestException, OSError) as exc:
            # Authentication refreshes and DNS/socket creation happen before
            # gspread can turn the failure into an APIError.  They are usually
            # transient during a busy crawler pass, so retry them as well.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(exc, APIError) and status not in {429, 500, 502, 503, 504}:
                raise
            error = exc
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt) + random.uniform(0, 0.5))
    raise error


def export_tab(worksheet, path):
    values = retry_google(lambda: worksheet.get_all_values(value_render_option=ValueRenderOption.formula))
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(values)
    os.chmod(path, 0o600)
    return len(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    # A backup is a read-only snapshot, but it must not be captured halfway
    # through a writer's multi-range update.
    lock = SheetsLock("backup_sheets")
    lock.__enter__()
    atexit.register(lock.__exit__, None, None, None)
    credentials = Credentials.from_service_account_file(CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(credentials)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "tabs": []}
    for name, (identifier, tabs) in BOOKS.items():
        book = retry_google(lambda: client.open_by_key(identifier))
        for tab in tabs:
            worksheet = retry_google(lambda: book.worksheet(tab))
            rows = export_tab(worksheet, directory / f"{name}_{TAB_NAMES[tab]}.csv")
            manifest["tabs"].append({"book": name, "tab": tab, "rows": rows})
    commercial_config = Path(__file__).resolve().parents[2] / "commercial_v1" / ".sheets.json"
    if commercial_config.exists():
        commercial = json.loads(commercial_config.read_text(encoding="utf-8"))
        book = retry_google(lambda: client.open_by_key(commercial["active"]["id"]))
        for operation, tab in commercial["active"].get("tabs", {}).items():
            worksheet = retry_google(lambda: book.worksheet(tab))
            rows = export_tab(worksheet, directory / f"commercial_{operation}.csv")
            manifest["tabs"].append({"book": "commercial", "tab": tab, "rows": rows})
        worksheet = retry_google(lambda: book.worksheet("Ручне додавання"))
        rows = export_tab(worksheet, directory / "commercial_manual.csv")
        manifest["tabs"].append({"book": "commercial", "tab": "Ручне додавання", "rows": rows})
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
