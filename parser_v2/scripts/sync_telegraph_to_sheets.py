from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import gspread
import psycopg2
import psycopg2.extras
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser_v2.services.sheets_lock import SheetsLock

CREDS = ROOT.parent / "olx-parser" / "ads-collector" / "real-estate-platform-484610-a5a172df3957.json"
RESIDENTIAL_BOOK_ID = "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8"
RESIDENTIAL_TABS = {"rent": "Оренда", "buy": "Продаж"}
COMMERCIAL_CONFIG = ROOT / "commercial_v1" / ".sheets.json"
DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin"}
OUTPUT_COLUMNS = {"ua": "Telegraph UA", "en": "Telegraph EN"}
URL_PATTERN = re.compile(r"^https://telegra\.ph/[A-Za-z0-9_-]+(?:\?.*)?$")
COMMERCIAL_APPROVED_COLUMNS = 58


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def retry(operation, attempts: int = 6):
    error = None
    for attempt in range(attempts):
        try:
            return operation()
        except APIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in {429, 500, 502, 503, 504}:
                raise
            error = exc
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt) + random.uniform(0, 0.5))
    raise error


def pending_publications(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT catalog, source, external_id, operation, locale, telegraph_url
        FROM block2.telegraph_publications
        WHERE synced_at IS NULL OR updated_at > synced_at
        ORDER BY updated_at, catalog, operation, source, external_id
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def listing_id(cursor, publication: dict) -> str | None:
    table = "active_listings" if publication["catalog"] == "residential" else "commercial_listings"
    cursor.execute(
        f"""
        SELECT id
        FROM {table}
        WHERE source=%s AND external_id=%s AND operation=%s AND status='active'
        LIMIT 1
        """,
        (publication["source"], publication["external_id"], publication["operation"]),
    )
    row = cursor.fetchone()
    return str(row["id"]) if row else None


def mark(cursor, publications: list[dict], synced: bool, error: str | None = None) -> None:
    for item in publications:
        cursor.execute(
            """
            UPDATE block2.telegraph_publications
            SET synced_at = CASE WHEN %s THEN now() ELSE NULL END,
                sync_error = %s
            WHERE catalog=%s AND source=%s AND external_id=%s AND operation=%s AND locale=%s
            """,
            (synced, error, item["catalog"], item["source"], item["external_id"], item["operation"], item["locale"]),
        )


def worksheet_for(client, catalog: str, operation: str):
    if catalog == "residential":
        book = retry(lambda: client.open_by_key(RESIDENTIAL_BOOK_ID))
        return retry(lambda: book.worksheet(RESIDENTIAL_TABS[operation]))
    config = json.loads(COMMERCIAL_CONFIG.read_text(encoding="utf-8"))
    book = retry(lambda: client.open_by_key(config["active"]["id"]))
    tab = config["active"]["tabs"][operation]
    return retry(lambda: book.worksheet(tab))


def output_indexes(ws, catalog: str) -> tuple[int, dict[str, int]]:




    if catalog == "commercial" and ws.col_count > COMMERCIAL_APPROVED_COLUMNS:
        retry(lambda: ws.resize(cols=COMMERCIAL_APPROVED_COLUMNS))
    header = retry(lambda: ws.row_values(1))
    missing = [name for name in OUTPUT_COLUMNS.values() if name not in header]
    if missing:
        start = len(header) + 1
        retry(lambda: ws.update(range_name=f"{column_name(start)}1:{column_name(start + len(missing) - 1)}1", values=[missing], value_input_option="USER_ENTERED"))
        header.extend(missing)
    if "ID" not in header:
        raise RuntimeError(f"{ws.title}: missing ID column")
    return header.index("ID") + 1, {locale: header.index(name) + 1 for locale, name in OUTPUT_COLUMNS.items()}


def sync_group(cursor, client, catalog: str, operation: str, publications: list[dict]) -> tuple[int, int]:
    ws = worksheet_for(client, catalog, operation)
    id_column, outputs = output_indexes(ws, catalog)
    ids = retry(lambda: ws.col_values(id_column))
    rows = {str(value).strip(): index for index, value in enumerate(ids[1:], 2) if str(value).strip()}
    updates = []
    missing = []
    for publication in publications:
        if not URL_PATTERN.fullmatch(publication["telegraph_url"]):
            missing.append(publication)
            continue
        identifier = listing_id(cursor, publication)
        row = rows.get(identifier or "")
        if row is None:
            missing.append(publication)
            continue
        column = outputs[publication["locale"]]
        updates.append((publication, {"range": f"{column_name(column)}{row}", "values": [[publication["telegraph_url"]]]}))
    for start in range(0, len(updates), 100):
        batch = updates[start:start + 100]
        retry(lambda batch=batch: ws.batch_update([entry[1] for entry in batch], value_input_option="USER_ENTERED"))
        mark(cursor, [entry[0] for entry in batch], True)
    if missing:
        mark(cursor, missing, False, "Active listing or valid Telegraph URL was not found")
    return len(updates), len(missing)


def main() -> None:
    if not CREDS.is_file():
        raise RuntimeError("Google service-account credentials were not found")
    if not COMMERCIAL_CONFIG.is_file():
        raise RuntimeError("Commercial Sheets configuration was not found")
    with psycopg2.connect(**DB) as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        publications = pending_publications(cursor)
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for publication in publications:
            groups[(publication["catalog"], publication["operation"])].append(publication)
        client = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets"]))
        result = {"synced": 0, "rejected": 0, "groups": {}}
        try:
            with SheetsLock("sync_telegraph_to_sheets"):
                for (catalog, operation), items in groups.items():
                    synced, rejected = sync_group(cursor, client, catalog, operation, items)
                    result["synced"] += synced
                    result["rejected"] += rejected
                    result["groups"][f"{catalog}:{operation}"] = {"synced": synced, "rejected": rejected}
        except RuntimeError as exc:
            if not str(exc).startswith("Sheets writer already running:"):
                raise
            result["busy"] = True
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
