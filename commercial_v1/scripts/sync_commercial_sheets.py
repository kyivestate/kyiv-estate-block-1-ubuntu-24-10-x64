from __future__ import annotations

import json
import os
import re
import random
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import gspread
import psycopg2.extras
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection
from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, HEADERS, SCOPES, TABS
from parser_v2.services.sheets_lock import SheetsLock
from manual_v1 import active_records, capture_sheet_notes


def safe(value: object, limit: int = 49000) -> str:
    if value is None:
        return ""
    result = str(value).strip()[:limit]
    if result.lower() in {"none", "null", "false"}:
        return ""
    return "'" + result if result.startswith(("=", "+", "-", "@")) else result


def number(value: object) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(numeric)
    except (TypeError, ValueError):
        return safe(value, 50)


def photo(url: object) -> str:
    value = safe(url, 1000)
    return f'=IMAGE("{value}")' if value.startswith("http") else ""


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def sheets_retry(action, attempts: int = 7):
    """Retry transient Google API failures without exceeding write quotas."""
    for attempt in range(attempts):
        try:
            return action()
        except Exception as exc:
            transient = any(code in str(exc) for code in (
                "429", "500", "503", "RESOURCE_EXHAUSTED", "timed out", "Timeout", "Connection",
            ))
            if not transient or attempt + 1 == attempts:
                raise
            time.sleep(min(64, 2 ** attempt) + random.random())


def floor_value(row: dict) -> str:
    floor = number(row.get("floor"))
    total = number(row.get("floors_total"))
    label = safe(row.get("floor_label"), 80)
    if floor and total:
        value = f"{floor} з {total}"
        return f"{label}; {value}" if label and label != floor else value
    if label:
        return label
    return floor


def status(value: object) -> str:
    return {"active": "Актуальне", "inactive": "Неактуальне", "quarantine": "На перевірці", "archived": "Архів"}.get(str(value), "На перевірці")


def record(row: dict) -> list[str]:
    return [
        safe(row.get("id"), 30), safe(row.get("external_id"), 60), photo(row.get("photo_url")), safe(row.get("source"), 30),
        "Оренда" if row.get("operation") == "rent" else "Продаж", status(row.get("status")), safe(row.get("commercial_type"), 80),
        safe(row.get("commercial_subtype"), 100), safe(row.get("url"), 1000), safe(row.get("title"), 500), safe(row.get("ai_title"), 500),
        safe(row.get("description")), safe(row.get("ai_description")), number(row.get("price_uah")), number(row.get("price_usd")), number(row.get("price_eur")),
        safe(row.get("price_period"), 20), number(row.get("price_per_m2_uah")), number(row.get("price_per_m2_usd")), number(row.get("price_per_m2_eur")), safe(row.get("price_per_m2_period"), 20),
        number(row.get("area_total_m2")), number(row.get("area_usable_m2")), floor_value(row), number(row.get("ceiling_height_m")), safe(row.get("district"), 100), safe(row.get("city"), 50),
        safe(row.get("street"), 160), safe(row.get("full_address"), 300), safe(row.get("permitted_use"), 300), safe(row.get("condition"), 100),
        safe(row.get("layout_type"), 100), number(row.get("electric_power_kw")), "Так" if row.get("generator") else "", "Так" if row.get("electricity_backup") else "",
        "Так" if row.get("ventilation") else "", "Так" if row.get("air_conditioning") else "", "Так" if row.get("facade") else "",
        "Так" if row.get("separate_entrance") else "", "Так" if row.get("showcase_windows") else "", "Так" if row.get("ramp") else "",
        "Так" if row.get("loading_dock") else "", number(row.get("parking_spaces")), safe(row.get("advertiser_type"), 40),
        safe(row.get("contact_name"), 100), safe(row.get("agency_name"), 160), safe(" ".join(row.get("phones") or []), 300),
        safe(row.get("commission_text"), 120), "Так" if row.get("vat_included") else "", number(row.get("opex_amount")),
        "Так" if row.get("utilities_included") else "", safe(row.get("created_at"), 40), safe(row.get("updated_at"), 40),
        safe(row.get("parsed_at"), 40), safe(", ".join(row.get("validation_errors") or []), 500), safe(row.get("comments"), 1000),
    ]


def update_rows(ws, updates: list[tuple[int, list[str]]]) -> int:
    for offset in range(0, len(updates), 10):


        payload = [{"range": f"A{row}:{column_name(len(HEADERS)-1)}{row}", "values": [values[:-1]]} for row, values in updates[offset:offset + 10]]
        if payload:
            sheets_retry(lambda: ws.batch_update(payload, value_input_option="USER_ENTERED"))
            time.sleep(1.2)
    return len(updates)


def delete_rows(ws, positions: list[int]) -> int:





    ordered = sorted(set(positions), reverse=True)
    ranges: list[list[int]] = []
    for position in ordered:
        if ranges and position == ranges[-1][0] - 1:
            ranges[-1][0] = position
        else:
            ranges.append([position, position])
    width = column_name(len(HEADERS) + 2)
    for offset in range(0, len(ranges), 25):
        clear_ranges = [f"A{start}:{width}{end}" for start, end in ranges[offset:offset + 25]]
        if clear_ranges:
            sheets_retry(lambda clear_ranges=clear_ranges: ws.batch_clear(clear_ranges), attempts=4)
            time.sleep(1.2)
    return len(ordered)


def rows_match(existing: list[object], expected: list[object]) -> bool:
    """Sheets returns typed numbers while the writer deliberately sends text.

    A strict Python comparison made every numeric commercial listing appear
    changed and held the global Sheets writer lock for many minutes.
    """
    ignored = {2, 51, 52, 53}
    for index, value in enumerate(expected[:-1]):
        if index in ignored:
            continue
        current = existing[index] if index < len(existing) else ""
        if index == 2:
            continue
        left = str(current).strip().lstrip("'")
        right = str(value).strip().lstrip("'")
        if left == right:
            continue
        try:
            if Decimal(left.replace(",", ".")) == Decimal(right.replace(",", ".")):
                continue
        except InvalidOperation:
            pass
        if left != right:
            return False
    return True


def ensure_row_capacity(ws, current: list[list[str]], appends: int, updates: list[tuple[int, list[str]]]) -> None:
    """Grow the worksheet before writing, including rows already referenced.

    Google Sheets can retain values past a manually reduced grid size.  In that
    state a normal update, not just an append, fails with "exceeds grid
    limits".  Keep ten spare manual rows after the last required row.
    """
    highest_update = max((position for position, _ in updates), default=1)
    required = max(len(current) + appends, highest_update) + 10
    if ws.row_count < required:
        ws.resize(rows=required)


def write_new_rows(ws, start_row: int, rows: list[list[str]]) -> int:
    """Write new records to explicit A:BD ranges.

    Google values.append tries to infer a logical table.  Sparse legacy rows
    made that inference start at column AZ, shifting complete listings to the
    right and expanding the grid.  Explicit ranges make row/column alignment
    deterministic.
    """
    width = column_name(len(HEADERS))
    for offset in range(0, len(rows), 25):
        batch = rows[offset:offset + 25]
        first = start_row + offset
        last = first + len(batch) - 1
        sheets_retry(lambda batch=batch, first=first, last=last: ws.update(
            range_name=f"A{first}:{width}{last}",
            values=batch,
            value_input_option="USER_ENTERED",
        ))
        time.sleep(1.2)
    return len(rows)


def enforce_column_ceiling(ws) -> None:
    """Keep the commercial workbook below Google's cell limit.

    Two Telegraph URL columns are approved after the 56 business columns.
    Historic faulty writes produced hundreds of duplicate trailing columns;
    they never contain canonical listing data and must not be allowed back.
    """
    approved_columns = len(HEADERS) + 2
    if ws.col_count <= approved_columns:
        return



    sheets_retry(lambda: ws.resize(cols=approved_columns))


def sync_tab(ws, rows: list[dict], allow_delete: bool) -> dict:
    enforce_column_ceiling(ws)
    header = sheets_retry(lambda: ws.row_values(1))
    if header == HEADERS[:-1]:
        sheets_retry(lambda: ws.update(range_name=f"A1:{column_name(len(HEADERS))}1", values=[HEADERS], value_input_option="USER_ENTERED"))
        header = HEADERS
    if header[:len(HEADERS)] != HEADERS:
        raise RuntimeError(f"{ws.title}: unexpected header; refusing to write")
    current = sheets_retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    with get_connection() as connection:
        capture_sheet_notes(connection, "commercial", current, 0, len(HEADERS)-1)
    by_id: dict[str, tuple[int, list[str]]] = {}
    duplicates = 0
    duplicate_positions: list[int] = []
    orphan_positions: list[int] = []
    for position, values in enumerate(current[1:], 2):
        identifier = str(values[HEADERS.index("ID")]).strip() if len(values) > HEADERS.index("ID") else ""
        if not identifier:
            if any(str(value).strip() for value in values):
                orphan_positions.append(position)
            continue
        if identifier in by_id:
            duplicates += 1
            duplicate_positions.append(position)
            continue
        by_id[identifier] = (position, values)
    expected = {safe(row["id"]): record(row) for row in rows}
    appends: list[list[str]] = []
    updates: list[tuple[int, list[str]]] = []
    for identifier, values in expected.items():
        present = by_id.get(identifier)
        if present is None:
            appends.append(values)
        elif not rows_match(present[1], values):
            updates.append((present[0], values))

    updated = update_rows(ws, updates)
    removed = 0
    if allow_delete and expected and os.getenv("PRESERVE_EXISTING_SHEET_ROWS", "").lower() not in {"1", "true", "yes"}:
        stale = [position for identifier, (position, _) in by_id.items() if identifier not in expected] + duplicate_positions + orphan_positions
        removed = delete_rows(ws, stale)
    current_after_delete = sheets_retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    ensure_row_capacity(ws, current_after_delete, len(appends), [])
    appended = write_new_rows(ws, len(current_after_delete) + 1, appends)
    sheets_retry(lambda: ws.spreadsheet.batch_update({"requests": [{"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": 0, "endIndex": ws.row_count}, "properties": {"pixelSize": 42}, "fields": "pixelSize"}}]}))
    return {"appended": appended, "updated": updated, "removed": removed, "duplicates": duplicates, "orphans": len(orphan_positions)}


def rows_for(operation: str) -> list[dict]:
    where = "operation=%s AND status='active'"
    with get_connection() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute(f"SELECT * FROM commercial_listings WHERE {where} ORDER BY updated_at DESC", (operation,))
        rows=[dict(row) for row in cursor.fetchall()]
        rows.extend(active_records(connection, 'commercial', operation))
        return rows


def main() -> int:
    if not CONFIG_PATH.exists():
        raise RuntimeError("Commercial Google Sheets are not configured")
    config = json.loads(CONFIG_PATH.read_text())
    client = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
    client.http_client.timeout = (20, 60)
    active = client.open_by_key(config["active"]["id"])
    result = {}
    try:
        with SheetsLock("commercial_sheets_sync", wait_seconds=900):
            active_tabs = {
                operation: config["active"].get("tabs", {}).get(operation, TABS[0] if operation == "rent" else TABS[1])
                for operation in ("rent", "buy")
            }




            for tab in set(active_tabs.values()):
                enforce_column_ceiling(active.worksheet(tab))
            for operation in ("rent", "buy"):
                active_tab = active_tabs[operation]
                active_result = sync_tab(active.worksheet(active_tab), rows_for(operation), allow_delete=True)
                result[operation] = active_result
    except RuntimeError as exc:


        if str(exc).startswith("Sheets writer already running:"):
            print(json.dumps({"status": "skipped", "reason": str(exc)}, ensure_ascii=False))
            return 0
        raise
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
