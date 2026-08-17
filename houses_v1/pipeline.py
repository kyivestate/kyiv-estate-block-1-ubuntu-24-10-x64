"""Independent houses collector. It shares extraction code but never uses apartment tables."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from parser_v2.config import cfg
from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.normalizers import normalize_listing
from houses_v1.persistence import get_conn, existing_external_ids, save_raw_listing, save_normalized_listing, merge_into_houses, clear_invalid_floor_pairs


def collect(source: str, operation: str, dry_run: bool, refresh_existing: bool = False) -> tuple[int, int]:
    http = OlxHttpClient(cfg.parser.request_timeout) if source == 'olx' else RieltorHttpClient(cfg.parser.request_timeout)
    parser = (OlxParser(http, operation, cfg.parser.olx_max_pages, {'Будинок'}) if source == 'olx'
              else RieltorParser(http, operation, cfg.parser.rieltor_max_pages, {'Будинок'}, geographic_scope='kyiv_region'))
    parsed = failed = 0
    conn = get_conn()
    try:
        entries = parser.collect_listing_urls()
        known = set() if dry_run else existing_external_ids(conn, source, operation)




        if not refresh_existing:
            entries = [entry for entry in entries if entry['external_id'] not in known]
        for entry in entries:
            raw, fields = parser.fetch_and_parse(entry['url'], entry['external_id'])
            if raw.parse_status != 'parsed':
                failed += 1
                if not dry_run:
                    save_raw_listing(conn, raw); conn.commit()
                continue
            listing = normalize_listing(raw, fields)
            if listing.property_type != 'Будинок':
                continue
            minimum_usd = 2_000 if operation == 'rent' else 100_000


            if listing.price_usd is None or listing.price_usd < minimum_usd:
                continue
            parsed += 1
            if not dry_run:
                listing.raw_listing_id = save_raw_listing(conn, raw)
                save_normalized_listing(conn, listing)
                conn.commit()
    finally:
        http.close(); conn.close()
    return parsed, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', choices=['olx','rieltor','all'], default='all')
    ap.add_argument('--operation', choices=['rent','buy','all'], default='all')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--refresh-existing', action='store_true', help='re-fetch known listings during a full coverage pass')
    args = ap.parse_args()
    run_started_at = datetime.now(timezone.utc)
    total = 0
    for source in (['olx','rieltor'] if args.source == 'all' else [args.source]):
        for operation in (['rent','buy'] if args.operation == 'all' else [args.operation]):
            parsed, failed = collect(source, operation, args.dry_run, args.refresh_existing)
            total += parsed
            print(f'{source}/{operation}: parsed={parsed} failed={failed}')
    if not args.dry_run:
        conn = get_conn()
        try:
            print(f'merged={merge_into_houses(conn, since=run_started_at)}')
            print(f'invalid_floor_pairs_cleared={clear_invalid_floor_pairs(conn)}')
        finally: conn.close()
    print(f'total={total}')


if __name__ == '__main__':
    main()
