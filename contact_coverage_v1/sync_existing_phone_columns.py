"""Fill only blank, existing phone cells in the three Active Google workbooks.

No worksheet, column, header, or source table is created or changed. The
default is a dry run; ``--apply`` is required for Google Sheets writes.
"""
from __future__ import annotations

import argparse
import json
import re

import gspread
import psycopg2.extras
from google.oauth2.service_account import Credentials

from contact_coverage_v1.config import cfg
from contact_coverage_v1.refresh import get_conn
from parser_v2.services.sheets_lock import SheetsLock


SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
BOOKS = {
    'apartments': {'id': '1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8', 'phone_header': 'Agent Phone'},
    'houses': {'id': '1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY', 'phone_header': 'Agent Phone'},
    'commercial': {'id': '15eFtcBjMYRAHLgDFP0u6Bo57ORVy8RWZ954Hp6bDDtw', 'phone_header': 'Телефони'},
}
TABS = {'rent': 'Оренда', 'buy': 'Продаж'}


def column_name(index: int) -> str:
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def phones_by_listing() -> dict[tuple[str, str], str]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT catalog, listing_id::text AS listing_id, contact_phone
              FROM contact_coverage_listings
             WHERE status='active' AND contact_method='public_phone' AND contact_phone<>''
        """)
        return {(row['catalog'], row['listing_id']): row['contact_phone'] for row in cur.fetchall()}


def pending_updates(sheet, catalog: str, phone_header: str, contacts: dict[tuple[str, str], str]) -> list[dict]:
    values = sheet.get_all_values(value_render_option='FORMULA')
    if not values:
        raise RuntimeError(f'{sheet.title}: missing header row')
    header = values[0]
    if 'ID' not in header or phone_header not in header:
        raise RuntimeError(f'{sheet.title}: expected ID and {phone_header!r} headers; refusing to write')
    id_index, phone_index = header.index('ID'), header.index(phone_header)
    phone_column = column_name(phone_index + 1)
    updates = []
    for row_number, row in enumerate(values[1:], 2):
        listing_id = row[id_index].strip() if len(row) > id_index else ''
        current_phone = row[phone_index].strip() if len(row) > phone_index else ''
        phone = re.sub(r'\s*,\s*', ' ', contacts.get((catalog, listing_id), '')).strip()
        if listing_id and phone and not current_phone:
            updates.append({'range': f'{phone_column}{row_number}', 'values': [[phone]]})
    return updates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='fill blank existing cells; default is read-only')
    args = parser.parse_args()
    if not cfg.credentials_file.is_file():
        raise RuntimeError('GOOGLE_CREDENTIALS_FILE is not configured or does not exist')

    contacts = phones_by_listing()
    client = gspread.authorize(Credentials.from_service_account_file(str(cfg.credentials_file), scopes=SCOPES))
    totals = {'mode': 'apply' if args.apply else 'dry-run', 'blank_phone_cells_to_fill': 0, 'by_catalog': {}}
    try:
        with SheetsLock('contact_coverage_existing_phone_sync'):
            for catalog, spec in BOOKS.items():
                book = client.open_by_key(spec['id'])
                catalog_updates = []
                for operation, tab_name in TABS.items():
                    sheet = book.worksheet(tab_name)
                    updates = pending_updates(sheet, catalog, spec['phone_header'], contacts)
                    catalog_updates.extend((sheet, updates))
                    totals['by_catalog'][f'{catalog}:{operation}'] = len(updates)
                if args.apply:
                    for sheet, updates in catalog_updates:
                        for start in range(0, len(updates), 50):
                            sheet.batch_update(updates[start:start + 50], value_input_option='RAW')
                totals['blank_phone_cells_to_fill'] += sum(len(updates) for _, updates in catalog_updates)
    except RuntimeError as exc:
        print(json.dumps({'mode': totals['mode'], 'sync': 'busy', 'reason': str(exc)}, ensure_ascii=False))
        return
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
