"""One-time additive migration: add the user-owned Comments column."""
from __future__ import annotations
import json
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, HEADERS
from parser_v2.services.sheets_lock import SheetsLock

def column_name(number: int) -> str:
    text=''
    while number:
        number,remainder=divmod(number-1,26); text=chr(65+remainder)+text
    return text

def main():
    config=json.loads(CONFIG_PATH.read_text())
    client=gspread.authorize(Credentials.from_service_account_file(str(CREDS),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
    with SheetsLock('commercial_comments_migration'):
        book=client.open_by_key(config['active']['id'])
        for tab in config['active']['tabs'].values():
            ws=book.worksheet(tab); current=ws.row_values(1)
            if current==HEADERS: print(f'{tab}: already migrated'); continue
            if current!=HEADERS[:-1]: raise RuntimeError(f'{tab}: unexpected header; no change made')
            ws.update(range_name=f'A1:{column_name(len(HEADERS))}1',values=[HEADERS],value_input_option='USER_ENTERED')
            print(f'{tab}: comments column added')
if __name__=='__main__': main()
