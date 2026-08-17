"""Idempotently repair the apartment-rent archive after an interrupted append.

It never clears the tab.  Every run removes only confirmed duplicate IDs and
appends only IDs absent from the sheet, so an API interruption is resumable.
"""
from __future__ import annotations
from collections import defaultdict
import psycopg2, psycopg2.extras
from cleaning.service import book, row_values
from parser_v2.services.sheets_lock import SheetsLock

def expected_records():
    with psycopg2.connect(host='localhost',port=5432,dbname='real_estate',user='admin') as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("select listing_id,snapshot from cleaning_archives where catalog='apartments' and snapshot->>'operation'='rent' order by listing_id")
            return [(str(r['listing_id']),dict(r['snapshot'])) for r in cur.fetchall()]

def main():
    expected=expected_records(); expected_by_id=dict(expected)
    if len(expected)!=16595 or len(expected_by_id)!=len(expected):
        raise RuntimeError(f'Unexpected canonical dataset: {len(expected)} rows')
    with SheetsLock('repair_archive_apartment_rent'):
        ws=book().worksheet('Квартири - Оренда')
        rows=ws.get_all_values(value_render_option='FORMULA')
        locations=defaultdict(list)
        for number,row in enumerate(rows[1:],2):
            if len(row)>3 and str(row[3]).strip(): locations[str(row[3]).strip()].append(number)
        unknown=set(locations)-set(expected_by_id)
        if unknown: raise RuntimeError(f'Unknown archive IDs; refusing repair: {list(unknown)[:5]}')

        duplicate_positions=sorted((pos for positions in locations.values() for pos in positions[1:]),reverse=True)
        for offset in range(0,len(duplicate_positions),100):
            batch=duplicate_positions[offset:offset+100]
            ws.spreadsheet.batch_update({'requests':[{'deleteDimension':{'range':{'sheetId':ws.id,'dimension':'ROWS','startIndex':p-1,'endIndex':p}}} for p in batch]})
        present=set(locations)
        missing=[record for identifier,record in expected if identifier not in present]
        for offset in range(0,len(missing),100):
            ws.append_rows([row_values('apartments',record,'historical inactive listing') for record in missing[offset:offset+100]],value_input_option='USER_ENTERED')
        print(f'duplicates_removed={len(duplicate_positions)} missing_appended={len(missing)} expected={len(expected)}')

if __name__=='__main__': main()
