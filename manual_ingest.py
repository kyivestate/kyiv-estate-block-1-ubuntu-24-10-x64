"""Thirty-minute import of the three human-entry tabs into PostgreSQL."""
from __future__ import annotations
import json
from pathlib import Path
import gspread, psycopg2
from google.oauth2.service_account import Credentials
from manual_v1 import MANUAL_HEADERS, MANUAL_TAB, active_records, ingest_manual_rows
from parser_v2.services.sheets_lock import SheetsLock

ROOT=Path(__file__).resolve().parent
CREDS=ROOT.parent/'olx-parser'/'ads-collector'/'real-estate-platform-484610-a5a172df3957.json'
BOOKS={'apartments':'1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8','houses':'1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY','commercial':json.loads((ROOT/'commercial_v1'/'.sheets.json').read_text())['active']['id']}

def publish_manual_rows(conn, client, catalog, identifiers):
 """Immediately publish accepted manual listings to their own rent/buy tab."""
 if not identifiers: return 0
 if catalog=='apartments':
  from parser_v2.scripts.run_all import row30 as render; last_column='AF'
 elif catalog=='houses':
  from houses_v1.sync_sheets import record_values as render; last_column='AD'
 else:
  from commercial_v1.scripts.sync_commercial_sheets import record as render; last_column='BD'
 book=client.open_by_key(BOOKS[catalog]); accepted={f'manual:{value}' for value in identifiers}; changed=0
 for operation,tab in (('rent','Оренда'),('buy','Продаж')):
  records=[row for row in active_records(conn,catalog,operation) if str(row['id']) in accepted]
  if not records: continue
  ws=book.worksheet(tab); current=ws.get_all_values(value_render_option='FORMULA')
  by_id={str(row[0]).strip():number for number,row in enumerate(current[1:],2) if row and str(row[0]).strip()}
  updates=[]; appends=[]
  for row in records:
   values=render(row); position=by_id.get(str(values[0]))
   if position: updates.append({'range':f'A{position}:{last_column}{position}','values':[values]})
   else: appends.append(values)
  for start in range(0,len(updates),50): ws.batch_update(updates[start:start+50],value_input_option='USER_ENTERED')
  for start in range(0,len(appends),100): ws.append_rows(appends[start:start+100],value_input_option='USER_ENTERED')
  changed += len(updates)+len(appends)
 return changed

def main():
 client=gspread.authorize(Credentials.from_service_account_file(str(CREDS),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
 try:
  lock=SheetsLock('manual_ingest'); lock.__enter__()
 except RuntimeError as exc:
  # Cleaning or a parser may be finishing a single atomic Sheet write.  The
  # next 30-minute run is safe; launchd must not report this as a failed job.
  print(f'manual_ingest=busy reason={exc}')
  return
 try:
  with psycopg2.connect(host='localhost',port=5432,dbname='real_estate',user='admin') as conn:
   for catalog,book_id in BOOKS.items():
    ws=client.open_by_key(book_id).worksheet(MANUAL_TAB)
    if ws.row_values(1)!=MANUAL_HEADERS: raise RuntimeError(f'{catalog}: manual header changed')
    accepted=ingest_manual_rows(conn,catalog,ws.get_all_values(value_render_option='FORMULA'))
    updates=[{'range':f'A{row}:A{row}','values':[[identifier]]} for row,identifier in accepted]
    updates += [{'range':f'M{row}:N{row}','values':[['Активне','створено системою']]} for row,_ in accepted]
    if updates: ws.batch_update(updates,value_input_option='USER_ENTERED')
    values=ws.get_all_values(); last=max((i for i,row in enumerate(values[1:],2) if any(str(v).strip() for v in row)),default=1)
    if ws.row_count < last+10:
     previous=ws.row_count; ws.add_rows(last+10-ws.row_count)
     ws.spreadsheet.batch_update({'requests':[{'updateDimensionProperties':{'range':{'sheetId':ws.id,'dimension':'ROWS','startIndex':previous,'endIndex':ws.row_count},'properties':{'pixelSize':42},'fields':'pixelSize'}}]})
    published=publish_manual_rows(conn,client,catalog,[identifier for _,identifier in accepted])
    print(f'{catalog}: accepted={len(accepted)} published={published}')
 finally:
  lock.__exit__(None,None,None)
if __name__=='__main__': main()
