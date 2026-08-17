"""One-time and repeatable migration of existing Active-sheet comments to DB."""
from __future__ import annotations
import json
from pathlib import Path
import gspread, psycopg2
from google.oauth2.service_account import Credentials
from manual_v1 import capture_sheet_notes
from commercial_v1.scripts.create_commercial_sheets import HEADERS as COMMERCIAL_HEADERS

ROOT=Path(__file__).resolve().parent
CREDS=ROOT.parent/'olx-parser'/'ads-collector'/'real-estate-platform-484610-a5a172df3957.json'
BOOKS={
 'apartments':('1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8',29),
 'houses':('1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY',29),
 'commercial':(json.loads((ROOT/'commercial_v1'/'.sheets.json').read_text())['active']['id'],len(COMMERCIAL_HEADERS)-1),
}
def main():
 client=gspread.authorize(Credentials.from_service_account_file(str(CREDS),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
 with psycopg2.connect(host='localhost',port=5432,dbname='real_estate',user='admin') as conn:
  for catalog,(book_id,comment_column) in BOOKS.items():
   book=client.open_by_key(book_id); count=0
   for tab in ('Оренда','Продаж'):
    count += capture_sheet_notes(conn,catalog,book.worksheet(tab).get_all_values(value_render_option='FORMULA'),0,comment_column)
   print(f'{catalog}: captured={count}')
if __name__=='__main__': main()
