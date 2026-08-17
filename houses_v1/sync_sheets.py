"""Incremental, non-destructive Google Sheets sync for Section 1.2 houses."""
from __future__ import annotations
import os
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
import psycopg2
import psycopg2.extras
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from parser_v2.services.sheets_lock import SheetsLock
from manual_v1 import active_records, capture_sheet_notes

load_dotenv(Path(__file__).with_name('.env'))
DB = dict(host='localhost', port=5432, dbname='real_estate', user='admin')
CREDS = os.getenv('GOOGLE_CREDENTIALS_FILE', '/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json')
SHEET_ID = os.getenv('HOUSES_ACTIVE_SHEET_ID', '')
HEADERS = ['ID','Ext ID','Фото','Source','Operation','Property Type','URL','Title','AI Title','Description','AI Description','UAH','USD','EUR','Rooms','Area','Floor','Floors Total','District','City','Street','Residential Complex','Metro','Agent Type','Agent Name','Agent Phone','Commission','Created At','Updated At','Коментарі']


def value(value, limit=49000):
    if value is None: return ''
    text = str(value).strip()[:limit]
    return "'" + text if text.startswith(('=','+','-','@')) else text


def record_values(row):
    photo_url = row.get('photo_url') or ''
    photo = f'=IMAGE("{photo_url}")' if photo_url.startswith('http') else ''
    return [value(row.get(k), 49000 if k in ('description','ai_description') else 500) for k in (
        'id','external_id')] + [photo] + [value(row.get(k), 49000 if k in ('description','ai_description') else 500) for k in (
        'source','operation','property_type','url','title','ai_title','description','ai_description','price_uah','price_usd','price_eur',
        'rooms','area','floor','floors_total','district','city','street','residential_complex','metro_station','agent_type','agent_name',
        'agent_phone','commission','created_at','updated_at','comments')]


def cells_match(existing, expected):
    left = str(existing).strip().lstrip("'")
    right = str(expected).strip().lstrip("'")
    if left == right:
        return True
    try:
        return Decimal(left.replace(',', '.')) == Decimal(right.replace(',', '.'))
    except InvalidOperation:
        return False


def rows_match(existing, expected):


    ignored = {2, 27, 28}
    return all(cells_match(existing[index] if index < len(existing) else '', expected[index])
               for index in range(29) if index not in ignored)


def delete_rows(sheet, positions):
    """Delete stale, duplicate and orphan rows using stable descending ranges."""
    ranges = []
    for row in sorted(set(positions), reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    requests = [
        {'deleteDimension': {'range': {
            'sheetId': sheet.id, 'dimension': 'ROWS',
            'startIndex': start - 1, 'endIndex': end,
        }}}
        for start, end in ranges
    ]
    for start in range(0, len(requests), 100):
        sheet.spreadsheet.batch_update({'requests': requests[start:start + 100]})
        time.sleep(1)
    return len(set(positions))


def clear_rows(sheet, positions):
    ranges = []
    for row in sorted(set(positions), reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    for start in range(0, len(ranges), 25):
        sheet.batch_clear([f'A{first}:AF{last}' for first, last in ranges[start:start + 25]])
        time.sleep(1)
    return len(set(positions))


def write_new_rows(sheet, start_row, rows):
    for offset in range(0, len(rows), 25):
        batch = rows[offset:offset + 25]
        first = start_row + offset
        last = first + len(batch) - 1
        sheet.update(range_name=f'A{first}:AD{last}', values=batch, value_input_option='USER_ENTERED')
        time.sleep(1)
    return len(rows)


def main():
    if not SHEET_ID:
        raise RuntimeError('HOUSES_ACTIVE_SHEET_ID is not configured')
    gc = gspread.authorize(Credentials.from_service_account_file(CREDS, scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
    gc.http_client.timeout = (20, 60)
    book = gc.open_by_key(SHEET_ID)
    try:
        lock = SheetsLock('houses_sheets_sync', wait_seconds=900)
        lock.__enter__()
    except RuntimeError as exc:

        print(f'sync=busy reason={exc}')
        return
    try:
        with psycopg2.connect(**DB) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for operation, tab in [('rent','Оренда'),('buy','Продаж')]:
                    cur.execute("SELECT * FROM houses_listings WHERE status='active' AND operation=%s ORDER BY updated_at DESC", (operation,))
                    records = [dict(row) for row in cur.fetchall()]
                    records.extend(active_records(conn, 'houses', operation))
                    try: sheet = book.worksheet(tab)
                    except gspread.WorksheetNotFound: sheet = book.add_worksheet(title=tab, rows=max(1000, len(records)+10), cols=len(HEADERS))
                    if sheet.col_count > len(HEADERS) + 2:
                        sheet.resize(cols=len(HEADERS) + 2)
                    header = sheet.row_values(1)




                    if header and header[:len(HEADERS)] != HEADERS:
                        raise RuntimeError(f'Unexpected header in {tab}; refusing to overwrite')
                    if not header: sheet.update('A1:AD1', [HEADERS], value_input_option='RAW')
                    existing = sheet.get_all_values(value_render_option='FORMULA')
                    capture_sheet_notes(conn, 'houses', existing, 0, 29)
                    by_id, duplicate_positions, orphan_positions = {}, [], []
                    for number, row in enumerate(existing[1:], 2):
                        identifier = str(row[0]).strip() if row else ''
                        if not identifier:
                            if any(str(value).strip() for value in row):
                                orphan_positions.append(number)
                            continue
                        if identifier in by_id:
                            duplicate_positions.append(number)
                            continue
                        by_id[identifier] = (number, row)
                    updates, appends = [], []
                    expected_ids = set()
                    for record in records:
                        values = record_values(record)
                        expected_ids.add(values[0])
                        found = by_id.get(values[0])
                        if found is None: appends.append(values)
                        elif not rows_match(found[1], values):

                            updates.append({'range':f'A{found[0]}:AC{found[0]}','values':[values[:29]]})
                    for start in range(0, len(updates), 50): sheet.batch_update(updates[start:start+50], value_input_option='USER_ENTERED')
                    stale_positions = [number for identifier, (number, _) in by_id.items() if identifier not in expected_ids]



                    removed = delete_rows(sheet, stale_positions + duplicate_positions + orphan_positions)
                    current_after_delete = sheet.get_all_values(value_render_option='FORMULA')
                    required_rows = len(current_after_delete) + len(appends) + 10
                    if sheet.row_count < required_rows:
                        sheet.resize(rows=required_rows)
                    appended = write_new_rows(sheet, len(current_after_delete) + 1, appends)
                    sheet.spreadsheet.batch_update({'requests':[{'updateDimensionProperties':{'range':{'sheetId':sheet.id,'dimension':'ROWS','startIndex':0,'endIndex':sheet.row_count},'properties':{'pixelSize':42},'fields':'pixelSize'}}]})
                    print(f'{tab}: active={len(records)} updated={len(updates)} appended={appended} removed={removed} duplicates={len(duplicate_positions)} orphans={len(orphan_positions)}')
    finally:
        lock.__exit__(None, None, None)


if __name__ == '__main__': main()
