"""Create safe manual-input tabs in every Active workbook without touching listings."""
from __future__ import annotations
import json
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from manual_v1 import MANUAL_HEADERS, MANUAL_TAB

ROOT=Path(__file__).resolve().parent
CREDS=ROOT.parent/'olx-parser'/'ads-collector'/'real-estate-platform-484610-a5a172df3957.json'
BOOKS={
 'apartments':'1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8',
 'houses':'1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY',
 'commercial':json.loads((ROOT/'commercial_v1'/'.sheets.json').read_text())['active']['id'],
}

def main():
 client=gspread.authorize(Credentials.from_service_account_file(str(CREDS),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
 for catalog,book_id in BOOKS.items():
  book=client.open_by_key(book_id)
  try: ws=book.worksheet(MANUAL_TAB)
  except gspread.WorksheetNotFound: ws=book.add_worksheet(title=MANUAL_TAB,rows=20,cols=len(MANUAL_HEADERS))
  header=ws.row_values(1)
  if header and header != MANUAL_HEADERS: raise RuntimeError(f'{catalog}: unexpected manual header')
  if not header: ws.update('A1:N1',[MANUAL_HEADERS],value_input_option='RAW')
  # Always maintain ten blank input rows after existing manual data.
  rows=ws.get_all_values(); last=max((i for i,row in enumerate(rows[1:],2) if any(str(v).strip() for v in row)),default=1)
  required=last+10
  if ws.row_count < required: ws.add_rows(required-ws.row_count)
  book.batch_update({'requests':[
   {'updateSheetProperties':{'properties':{'sheetId':ws.id,'gridProperties':{'frozenRowCount':1}},'fields':'gridProperties.frozenRowCount'}},
   {'repeatCell':{'range':{'sheetId':ws.id,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}},
   {'repeatCell':{'range':{'sheetId':ws.id,'startRowIndex':1,'endColumnIndex':len(MANUAL_HEADERS)},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'MIDDLE'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}},
  ]})
  print(f'{catalog}: {MANUAL_TAB} ready, blank_rows>=10')
if __name__=='__main__': main()
