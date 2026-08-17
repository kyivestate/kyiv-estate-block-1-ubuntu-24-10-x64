import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import gspread
import psycopg2
import psycopg2.extras
from google.oauth2.service_account import Credentials

from parser_v2.services.process_lock import acquire_process_lock
from parser_v2.services.sheets_lock import SheetsLock


ACTIVE_SHEET_ID = "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8"
LIFECYCLE_SHEET_ID = "1B0O2rTAcbfrrMxE1XX-lHDhqi2qt_Mg-U5usql975gg"
CREDS = "/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json"
TABS = {"rent": "Оренда", "buy": "Продаж"}
HEADERS = [
    "ID", "Джерело", "Тип угоди", "Статус", "Фото", "Тип нерухомості", "URL",
    "Заголовок", "Опис оголошення", "Ціна UAH", "Ціна USD", "Ціна EUR", "Кімнат",
    "Площа", "Поверх", "Поверхів", "Район", "Адреса", "Вулиця", "ЖК",
    "Агенція/Власник", "Ім'я агента", "Телефон", "Комісія", "Створено", "Оновлено",
    "Коментарі", "Telegraph UA", "Telegraph EN", "CSV оголошення",
]
ACTIVE_HEADERS = [
    "ID", "Ext ID", "Фото", "Source", "Operation", "Property Type", "URL",
    "Title", "AI Title", "Description", "AI Description", "UAH", "USD", "EUR",
    "Rooms", "Area", "Floor", "Floors Total", "District", "City", "Street",
    "Residential Complex", "Metro", "Agent Type", "Agent Name", "Agent Phone",
    "Commission", "Created At", "Updated At", "Коментарі", "Telegraph UA", "Telegraph EN",
]


def text(value, limit=49000):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"none", "null", "false"}:
        return ""
    value = value[:limit]
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def number(value):
    if value is None or value == "":
        return ""
    try:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(numeric)
    except (TypeError, ValueError):
        return text(value, 50)


def status_label(status):
    return {
        "active": "Актуальне",
        "inactive": "Неактуальне",
        "quarantine": "На перевірці",
        "archived": "Архів",
    }.get(text(status).lower(), "На перевірці")


def photo(value):
    url = text(value, 1000)
    return f'=IMAGE("{url}")' if url.startswith("http") else ""


def address(row):
    parts = [text(row.get("city"), 80), text(row.get("street"), 160)]
    return ", ".join(part for part in parts if part)


def record(row):
    operation = "Оренда" if row["operation"] == "rent" else "Продаж"
    return [
        text(row.get("id"), 30), text(row.get("source"), 30), operation,
        status_label(row.get("status")), photo(row.get("photo_url")), text(row.get("property_type"), 80),
        text(row.get("url"), 1000), text(row.get("ai_title") or row.get("title"), 300),
        text(row.get("ai_description") or row.get("description")), number(row.get("price_uah")),
        number(row.get("price_usd")), number(row.get("price_eur")), number(row.get("rooms")),
        number(row.get("area")), number(row.get("floor")), number(row.get("floors_total")),
        text(row.get("district"), 100), address(row), text(row.get("street"), 160),
        text(row.get("residential_complex"), 160), text(row.get("agent_type"), 60),
        text(row.get("agent_name"), 160), text(row.get("agent_phone"), 80), text(row.get("commission"), 80),
        text(row.get("created_at"), 30), text(row.get("updated_at"), 30), text(row.get("comments"), 1000),
        "", "", "",
    ]


def same(left, right):
    return text(left) == text(right)


def update_cells(worksheet, cells):
    for start in range(0, len(cells), 500):
        worksheet.update_cells(cells[start:start + 500], value_input_option="USER_ENTERED")
        time.sleep(1)


def delete_rows(worksheet, rows):
    if not rows:
        return 0
    ranges = []
    for row in sorted(rows, reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    requests = []
    for start, end in ranges:
        requests.append({"deleteDimension": {"range": {
            "sheetId": worksheet.id, "dimension": "ROWS", "startIndex": start - 1, "endIndex": end,
        }}})
    for start in range(0, len(requests), 100):
        worksheet.spreadsheet.batch_update({"requests": requests[start:start + 100]})
        time.sleep(1)
    return len(rows)


def fetch_rows():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""SELECT id, external_id, source, operation, status, property_type, url, title,
            ai_title, description, ai_description, price_uah, price_usd, price_eur, rooms, area, floor,
            floors_total, district, city, street, residential_complex, agent_type, agent_name, agent_phone,
            commission, created_at, updated_at, comments, photo_url
            FROM active_listings WHERE source NOT LIKE 'findly%%' ORDER BY id""")
        rows = [dict(row) for row in cursor.fetchall()]
        return rows
    finally:
        conn.close()


def sync_lifecycle(books, rows):
    by_operation = defaultdict(list)
    for row in rows:
        by_operation[row["operation"]].append(row)
    result = {"appended": 0, "updated": 0, "duplicates": 0}
    for operation, title in TABS.items():
        worksheet = books["lifecycle"].worksheet(title)
        if worksheet.row_values(1) != HEADERS:
            raise RuntimeError(f"{title}: unexpected lifecycle schema; refusing to write")
        columns = worksheet.batch_get(["A:A", "D:D", "Z:Z"])
        ids = columns[0] if columns else []
        statuses = columns[1] if len(columns) > 1 else []
        updated_at = columns[2] if len(columns) > 2 else []
        by_id = {}
        for index, identifier in enumerate(ids[1:], 2):
            identifier = identifier[0].strip() if identifier else ""
            if identifier:
                if identifier in by_id:
                    result["duplicates"] += 1
                else:
                    status = statuses[index - 1][0] if len(statuses) >= index and statuses[index - 1] else ""
                    updated = updated_at[index - 1][0] if len(updated_at) >= index and updated_at[index - 1] else ""
                    by_id[identifier] = (index, status, updated)
        appends = []
        cells = []
        for row in by_operation[operation]:
            expected = record(row)
            identifier = expected[0]
            existing = by_id.get(identifier)
            if existing is None:
                appends.append(expected)
                continue
            row_number, current_status, current_updated_at = existing
            for column, actual in ((3, current_status), (25, current_updated_at)):
                if not same(actual, expected[column]):
                    cells.append(gspread.Cell(row_number, column + 1, expected[column]))
                    result["updated"] += 1
        for start in range(0, len(appends), 250):
            worksheet.append_rows(appends[start:start + 250], value_input_option="USER_ENTERED")
            result["appended"] += len(appends[start:start + 250])
            time.sleep(1)
        update_cells(worksheet, cells)
    return result


def active_cell(row, name):
    try:
        index = ACTIVE_HEADERS.index(name)
    except ValueError:
        return ""
    return row[index] if len(row) > index else ""


def active_photo(row):
    value = active_cell(row, "Фото")
    match = re.fullmatch(r'=IMAGE\("(https?://[^"]+)"\)', str(value).strip())
    return photo(match.group(1)) if match else ""


def orphan_record(row, operation):
    title = active_cell(row, "AI Title") or active_cell(row, "Title")
    description = active_cell(row, "AI Description") or active_cell(row, "Description")
    city = text(active_cell(row, "City"), 80)
    street = text(active_cell(row, "Street"), 160)
    return [
        text(active_cell(row, "ID"), 30), text(active_cell(row, "Source"), 30),
        "Оренда" if operation == "rent" else "Продаж", "Неактуальне", active_photo(row),
        text(active_cell(row, "Property Type"), 80), text(active_cell(row, "URL"), 1000),
        text(title, 300), text(description), number(active_cell(row, "UAH")),
        number(active_cell(row, "USD")), number(active_cell(row, "EUR")),
        number(active_cell(row, "Rooms")), number(active_cell(row, "Area")),
        number(active_cell(row, "Floor")), number(active_cell(row, "Floors Total")),
        text(active_cell(row, "District"), 100), ", ".join(part for part in (city, street) if part),
        street, text(active_cell(row, "Residential Complex"), 160),
        text(active_cell(row, "Agent Type"), 60), text(active_cell(row, "Agent Name"), 160),
        text(active_cell(row, "Agent Phone"), 80), text(active_cell(row, "Commission"), 80),
        text(active_cell(row, "Created At"), 30), text(active_cell(row, "Updated At"), 30),
        text(active_cell(row, "Коментарі"), 1000), "", "", "",
    ]


def migrate_orphans_to_lifecycle(books, rows):
    known_ids = defaultdict(set)
    for row in rows:
        known_ids[row["operation"]].add(text(row["id"]))
    result = {"appended": 0, "present": 0, "ids": defaultdict(set)}
    for operation, title in TABS.items():
        active = books["active"].worksheet(title)
        lifecycle = books["lifecycle"].worksheet(title)
        active_values = active.get_all_values(value_render_option="FORMULA")
        lifecycle_ids_column = lifecycle.col_values(1)
        if not active_values or active_values[0] != ACTIVE_HEADERS:
            raise RuntimeError(f"{title}: unexpected active-sheet schema; refusing orphan migration")
        if lifecycle.row_values(1) != HEADERS:
            raise RuntimeError(f"{title}: unexpected lifecycle schema; refusing orphan migration")
        lifecycle_ids = {identifier.strip() for identifier in lifecycle_ids_column[1:] if identifier.strip()}
        planned = set()
        appends = []
        for row in active_values[1:]:
            identifier = text(active_cell(row, "ID"), 30)
            if not identifier or identifier in known_ids[operation]:
                continue
            result["ids"][operation].add(identifier)
            if identifier in lifecycle_ids or identifier in planned:
                result["present"] += 1
                continue
            appends.append(orphan_record(row, operation))
            planned.add(identifier)
        for start in range(0, len(appends), 250):
            lifecycle.append_rows(appends[start:start + 250], value_input_option="USER_ENTERED")
            result["appended"] += len(appends[start:start + 250])
            time.sleep(1)
    return result


def remove_inactive_from_active(books, rows, orphan_ids):
    active_ids = defaultdict(set)
    known_ids = defaultdict(set)
    for row in rows:
        known_ids[row["operation"]].add(text(row["id"]))
        if row["status"] == "active":
            active_ids[row["operation"]].add(text(row["id"]))
    removed = 0
    for operation, title in TABS.items():
        worksheet = books["active"].worksheet(title)
        if worksheet.row_values(1) != ACTIVE_HEADERS:
            raise RuntimeError(f"{title}: unexpected active-sheet schema; refusing to delete")
        ids = worksheet.col_values(1)
        stale = [
            index for index, identifier in enumerate(ids[1:], 2)
            if identifier.strip() and (
                (identifier.strip() in known_ids[operation] and identifier.strip() not in active_ids[operation])
                or identifier.strip() in orphan_ids[operation]
            )
        ]
        removed += delete_rows(worksheet, stale)
    return removed


def main():
    process_lock = acquire_process_lock("sync_listing_lifecycle")
    credentials = Credentials.from_service_account_file(CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(credentials)
    books = {
        "active": client.open_by_key(ACTIVE_SHEET_ID),
        "lifecycle": client.open_by_key(LIFECYCLE_SHEET_ID),
    }
    rows = fetch_rows()
    with SheetsLock("sync_listing_lifecycle", wait_seconds=900):
        lifecycle = sync_lifecycle(books, rows)
        orphans = migrate_orphans_to_lifecycle(books, rows)
        removed = remove_inactive_from_active(books, rows, orphans["ids"])
    print(f"lifecycle_appended={lifecycle['appended']} lifecycle_updated_cells={lifecycle['updated']} lifecycle_duplicate_ids={lifecycle['duplicates']} orphan_migrated={orphans['appended']} orphan_present={orphans['present']} active_rows_removed={removed}")


if __name__ == "__main__":
    main()
