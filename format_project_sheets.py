"""Apply one legible, fixed row height to every Active and Archive worksheet."""
from __future__ import annotations
import json
import os
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from parser_v2.services.sheets_lock import SheetsLock

ROOT=Path(__file__).resolve().parent
CREDS=Path(os.environ['GOOGLE_CREDENTIALS_FILE'])
ROW_HEIGHT=42
BOOKS={
 'apartments':'1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8',
 'houses':'1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY',
 'commercial':json.loads((ROOT/'commercial_v1'/'.sheets.json').read_text())['active']['id'],
 'archive':'1h_NUcFIx8Fbm_HuIYea2L_IK4rAad5jtuBE4Hf_DkrY',
}

def main():
 client=gspread.authorize(Credentials.from_service_account_file(str(CREDS),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
 with SheetsLock('format_project_sheets'):
  for name,identifier in BOOKS.items():
   book=client.open_by_key(identifier); requests=[]
   for ws in book.worksheets():
    end=max(ws.row_count,1)
    requests.extend((
      {'repeatCell':{'range':{'sheetId':ws.id,'startRowIndex':0,'endRowIndex':end},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'MIDDLE'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}},
      {'updateDimensionProperties':{'range':{'sheetId':ws.id,'dimension':'ROWS','startIndex':0,'endIndex':end},'properties':{'pixelSize':ROW_HEIGHT},'fields':'pixelSize'}},
    ))
   book.batch_update({'requests':requests})
   print(f'{name}: formatted_tabs={len(book.worksheets())} row_height={ROW_HEIGHT}')
if __name__=='__main__': main()
