"""Safe rotating availability checks and idempotent Google Sheets archival."""
from __future__ import annotations
import json, os
from pathlib import Path
import psycopg2, psycopg2.extras, gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.sheets_lock import SheetsLock
from manual_v1 import apply_schema

load_dotenv(Path(__file__).with_name('.env'))
ARCHIVE_ID=os.environ['CLEANING_ARCHIVE_SHEET_ID']
CREDS=os.environ['GOOGLE_CREDENTIALS_FILE']
HEADERS=['Каталог','Архівовано','Причина','ID','Ext ID','Джерело','Операція','URL','Тип','Заголовок','AI Title','Опис','AI Опис','Ціна UAH','Ціна USD','Ціна EUR','Площа','Поверх','Поверхів','Район','Місто','Вулиця','Дані JSON']
SCOPE={
 ('apartments','rent'):('active_listings','Квартири - Оренда',"property_type='Квартира'"),
 ('apartments','buy'):('active_listings','Квартири - Продаж',"property_type='Квартира'"),
 ('houses','rent'):('houses_listings','Будинки - Оренда','true'),
 ('houses','buy'):('houses_listings','Будинки - Продаж','true'),
 ('commercial','rent'):('commercial_listings','Комерція - Оренда','true'),
 ('commercial','buy'):('commercial_listings','Комерція - Продаж','true'),
}

def value(v): return '' if v is None else str(v)
def row_values(catalog, row, reason):
    return [catalog, value(row.get('updated_at')), reason, value(row.get('id')),value(row.get('external_id')),value(row.get('source')),value(row.get('operation')),value(row.get('url')),value(row.get('property_type') or row.get('commercial_type')),value(row.get('title')),value(row.get('ai_title')),value(row.get('description')),value(row.get('ai_description')),value(row.get('price_uah')),value(row.get('price_usd')),value(row.get('price_eur')),value(row.get('area') or row.get('area_total_m2')),value(row.get('floor')),value(row.get('floors_total')),value(row.get('district')),value(row.get('city')),value(row.get('street')),json.dumps(row,ensure_ascii=False,default=str)]

def attach_user_notes(conn, catalog, rows):
    """Keep human notes when an Active row is moved to Archive."""
    if not rows:
        return rows
    apply_schema(conn)
    identifiers=[str(row['id']) for row in rows]
    with conn.cursor() as cur:
        cur.execute('SELECT listing_id,note FROM listing_user_notes WHERE catalog=%s AND listing_id=ANY(%s)',(catalog,identifiers))
        notes=dict(cur.fetchall())
    for row in rows:
        note=notes.get(str(row['id']))
        if note:
            row['comments']=note
    return rows

def book():
    return sheets_client().open_by_key(ARCHIVE_ID)
def sheets_client():
    return gspread.authorize(Credentials.from_service_account_file(CREDS,scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
def archive_tabs(b):
    found={w.title:w for w in b.worksheets()}
    for _,tab,_ in SCOPE.values():
        ws=found.get(tab) or b.add_worksheet(title=tab,rows=1000,cols=len(HEADERS))
        if not ws.row_values(1): ws.update(range_name='A1:W1',values=[HEADERS],value_input_option='RAW')
        elif ws.row_values(1)!=HEADERS: raise RuntimeError(f'archive header changed: {tab}')
    try:
        default=b.worksheet('Аркуш1')
        if not any(any(str(c).strip() for c in r) for r in default.get('A1:W3')): b.del_worksheet(default)
    except gspread.WorksheetNotFound: pass

def candidates(cur,catalog,operation,limit):
    table,_,extra=SCOPE[(catalog,operation)]
    cur.execute(f'''SELECT l.* FROM {table} l LEFT JOIN cleaning_listing_checks c ON c.catalog=%s AND c.listing_id=l.id
      WHERE l.status='active' AND l.operation=%s AND ({extra}) AND l.source IN ('olx','rieltor') AND l.url LIKE 'http%%'
      ORDER BY c.checked_at NULLS FIRST,l.id LIMIT %s''',(catalog,operation,limit))
    return [dict(r) for r in cur.fetchall()]

def historical_inactive(cur,catalog,operation,limit):
    """Inactive rows from before Cleaning was introduced.

    They are deliberately handled separately from availability checks: their
    status was already set by an earlier pipeline, so re-checking every old URL
    would delay the archive for days and create unnecessary source traffic.
    """
    table,_,extra=SCOPE[(catalog,operation)]
    cur.execute(f'''SELECT l.* FROM {table} l
      LEFT JOIN cleaning_archives a ON a.catalog=%s AND a.listing_id=l.id
      WHERE l.status IN ('inactive','archived') AND l.operation=%s AND ({extra})
        AND a.listing_id IS NULL
      ORDER BY l.updated_at NULLS LAST,l.id LIMIT %s''',(catalog,operation,limit))
    return [dict(r) for r in cur.fetchall()]

def archive_historical_scope(conn,b,catalog,operation,limit):
    """Append one idempotent, resumable batch of historical inactive rows."""
    _,tab,_=SCOPE[(catalog,operation)]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        rows=historical_inactive(cur,catalog,operation,limit)
    if not rows:
        print(f'{catalog}/{operation}: historical=0')
        return 0



    rows=attach_user_notes(conn,catalog,rows)
    ws=b.worksheet(tab)


    present={str(v).strip() for v in ws.col_values(4)[1:] if str(v).strip()}
    to_append=[r for r in rows if str(r['id']) not in present]
    if to_append:
        ws.append_rows([row_values(catalog,r,'historical inactive listing') for r in to_append],value_input_option='USER_ENTERED')
    with conn.cursor() as cur:
        for row in rows:
            cur.execute('''INSERT INTO cleaning_archives(catalog,listing_id,reason,snapshot)
              VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (catalog,row['id'],'historical_inactive',json.dumps(row,ensure_ascii=False,default=str)))
    conn.commit()

    remove_from_active(catalog,operation,[r['id'] for r in rows])
    print(f'{catalog}/{operation}: historical_archived={len(rows)} appended={len(to_append)}')
    return len(rows)
def check(row,client):
    try: return client.get(row['url'])[0],''
    except Exception as e: return None,str(e)[:500]
def remove_from_active(catalog,operation,identifiers):
    active_id={'apartments':'1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8','houses':'1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY','commercial':'15eFtcBjMYRAHLgDFP0u6Bo57ORVy8RWZ954Hp6bDDtw'}[catalog]
    ws=sheets_client().open_by_key(active_id).worksheet('Оренда' if operation=='rent' else 'Продаж')
    target={str(x) for x in identifiers}
    rows=sorted((i for i,v in enumerate(ws.col_values(1)[1:],2) if str(v).strip() in target),reverse=True)
    for start in range(0,len(rows),100):
        ws.spreadsheet.batch_update({'requests':[{'deleteDimension':{'range':{'sheetId':ws.id,'dimension':'ROWS','startIndex':i-1,'endIndex':i}}} for i in rows[start:start+100]]})
def process_scope(conn,b,catalog,operation,limit):
    table,tab,_=SCOPE[(catalog,operation)]; source_clients={'olx':OlxHttpClient(30),'rieltor':RieltorHttpClient(30)}
    source_clients['rieltor']._min_delay=5.0; archived=[]; processed=0; consecutive_throttled=0
    try:
      with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
       for row in candidates(cur,catalog,operation,limit):
        status,error=check(row,source_clients[row['source']])
        processed += 1
        consecutive_throttled = consecutive_throttled + 1 if status == 429 else 0
        cur.execute('''INSERT INTO cleaning_listing_checks(catalog,listing_id,checked_at,http_status,consecutive_missing,last_error)
          VALUES(%s,%s,NOW(),%s,CASE WHEN %s IN (404,410) THEN 1 ELSE 0 END,%s)
          ON CONFLICT(catalog,listing_id) DO UPDATE SET checked_at=EXCLUDED.checked_at,http_status=EXCLUDED.http_status,last_error=EXCLUDED.last_error,
          consecutive_missing=CASE WHEN EXCLUDED.http_status IN (404,410) THEN cleaning_listing_checks.consecutive_missing+1 WHEN EXCLUDED.http_status BETWEEN 200 AND 399 THEN 0 ELSE cleaning_listing_checks.consecutive_missing END RETURNING consecutive_missing''',(catalog,row['id'],status,status,error))
        missing=cur.fetchone()['consecutive_missing']
        if status in (404,410) and missing>=2:
         if table=='commercial_listings':
          cur.execute(f"UPDATE {table} SET status='inactive',updated_at=NOW() WHERE id=%s AND status='active'",(row['id'],))
         else:
          cur.execute(f"UPDATE {table} SET status='inactive',comments=COALESCE(NULLIF(comments,''),'') || %s,updated_at=NOW() WHERE id=%s AND status='active'",(f' cleaning_http_{status}_confirmed',row['id']))
         if cur.rowcount:
          cur.execute('INSERT INTO cleaning_archives(catalog,listing_id,reason,snapshot) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(catalog,row['id'],f'http_{status}_confirmed',json.dumps(row,ensure_ascii=False,default=str))); archived.append(row)
        if consecutive_throttled >= 3:
         print(f'{catalog}/{operation}: source_throttled=429 after={processed}; remaining checks deferred')
         break
       conn.commit()
      if archived:
       archived=attach_user_notes(conn,catalog,archived)
       ws=b.worksheet(tab); ws.append_rows([row_values(catalog,r,'source removed after two HTTP confirmations') for r in archived],value_input_option='USER_ENTERED')

       remove_from_active(catalog,operation,[r['id'] for r in archived])
      print(f'{catalog}/{operation}: checked={processed} archived={len(archived)}')
    finally:
      [c.close() for c in source_clients.values()]

def main():
  limit=int(os.getenv('CLEANING_LIMIT_PER_SCOPE','40'))
  try:
    with psycopg2.connect(host='localhost',port=5432,dbname='real_estate',user='admin') as conn, SheetsLock('cleaning'):
      b=book(); archive_tabs(b)
      for catalog,operation in SCOPE: process_scope(conn,b,catalog,operation,limit)
  except RuntimeError as exc:


    if str(exc).startswith('Sheets writer already running:'):
      print(f'cleaning_skipped={exc}')
      return
    raise
if __name__=='__main__': main()
