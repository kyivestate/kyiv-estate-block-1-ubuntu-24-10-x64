"""Resumable archival of listings that were already inactive before Cleaning."""
from __future__ import annotations
import argparse
import psycopg2
from cleaning.service import SCOPE, SheetsLock, archive_historical_scope, archive_tabs, book

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch-size',type=int,default=250)
    parser.add_argument('--batches',type=int,default=1)
    args=parser.parse_args()
    if args.batch_size < 1 or args.batches < 1:
        raise SystemExit('batch-size and batches must be positive')
    try:
        with psycopg2.connect(host='localhost',port=5432,dbname='real_estate',user='admin') as conn, SheetsLock('cleaning_historical_archive'):
            spreadsheet=book(); archive_tabs(spreadsheet)
            moved=0
            for _ in range(args.batches):
                progressed=0
                for catalog,operation in SCOPE:
                    count=archive_historical_scope(conn,spreadsheet,catalog,operation,args.batch_size)
                    moved+=count; progressed+=count
                if not progressed:
                    break
            print(f'historical archive complete: moved={moved}')
    except RuntimeError as exc:


        print(f'historical_archive_deferred={exc}')

if __name__=='__main__': main()
