"""Append/update only sync for dedicated Findly workbooks."""
from __future__ import annotations

from pathlib import Path

import gspread
import psycopg2.extras
from google.oauth2.service_account import Credentials

from findly_v1.config import cfg
from findly_v1.persistence import get_conn
from parser_v2.services.sheets_lock import SheetsLock

HEADERS = ['ID', 'Ext ID', 'Фото', 'Source', 'Origin Source', 'Operation', 'Property Type', 'URL', 'Title', 'AI Title', 'Description', 'AI Description', 'UAH', 'USD', 'EUR', 'Rooms', 'Area', 'Floor', 'Floors Total', 'District', 'City', 'Street', 'Address', 'Contact Name', 'Contact Phone', 'Commission', 'Status', 'First Seen', 'Last Seen', 'Updated At', 'Comments']


def cell(value: object, limit: int = 49_000) -> str:
    value = '' if value is None else str(value).strip()[:limit]
    return "'" + value if value.startswith(('=', '+', '-', '@')) else value


def values(row: dict) -> list[str]:
    photo_url = row.get('photo_url') or ''
    image = f'=IMAGE("{photo_url}")' if str(photo_url).startswith('http') else ''
    fields = ('id','external_id','source','origin_source','operation','property_type','url','title','ai_title','description','ai_description','price_uah','price_usd','price_eur','rooms','area','floor','floors_total','district','city','street','full_address','contact_name','contact_phone','commission','status','first_seen_at','last_seen_at','updated_at','comments')
    result = [cell(row.get('id')), cell(row.get('external_id')), image]
    result.extend(cell(row.get(field)) for field in fields[2:])
    return result


def sync_book(sheet_id: str, include_inactive: bool) -> None:
    if not sheet_id:
        raise RuntimeError('Dedicated Findly Sheets ID is not configured')
    if not cfg.credentials_file.is_file():
        raise RuntimeError('GOOGLE_CREDENTIALS_FILE is not configured or does not exist')
    credentials = Credentials.from_service_account_file(str(cfg.credentials_file), scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
    book = gspread.authorize(credentials).open_by_key(sheet_id)
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for operation, tab in (('rent', 'Оренда'), ('buy', 'Продаж')):
            predicate = "operation=%s" if include_inactive else "operation=%s AND status='active'"
            cur.execute(f'SELECT * FROM findly_listings WHERE {predicate} ORDER BY updated_at DESC', (operation,))
            records = [dict(record) for record in cur.fetchall()]
            try:
                sheet = book.worksheet(tab)
            except gspread.WorksheetNotFound:
                sheet = book.add_worksheet(title=tab, rows=max(1000, len(records) + 10), cols=len(HEADERS))
            header = sheet.row_values(1)
            if header and header != HEADERS:
                raise RuntimeError(f'Unexpected header in Findly {tab}; refusing to overwrite')
            if not header:
                sheet.update(f'A1:AE1', [HEADERS], value_input_option='RAW')
            existing = sheet.get_all_values(value_render_option='FORMULA')
            by_id = {str(row[0]).strip(): (index, row) for index, row in enumerate(existing[1:], 2) if row and str(row[0]).strip()}
            updates, appends = [], []
            for record in records:
                record_values = values(record)
                found = by_id.get(record_values[0])
                if found is None:
                    appends.append(record_values)
                elif found[1][:len(record_values)] != record_values:
                    updates.append({'range': f'A{found[0]}:AE{found[0]}', 'values': [record_values]})
            for start in range(0, len(updates), 50):
                sheet.batch_update(updates[start:start + 50], value_input_option='USER_ENTERED')
            for start in range(0, len(appends), 300):
                sheet.append_rows(appends[start:start + 300], value_input_option='USER_ENTERED')
            print(f'{tab}: records={len(records)} updated={len(updates)} appended={len(appends)}')


def main() -> None:

    with SheetsLock('findly_sheets_sync'):
        sync_book(cfg.active_sheet_id, include_inactive=False)
        if cfg.lifecycle_sheet_id:
            sync_book(cfg.lifecycle_sheet_id, include_inactive=True)


if __name__ == '__main__':
    main()
