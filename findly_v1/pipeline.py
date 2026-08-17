"""Collect Findly into the isolated v1 tables.

The default path is metadata-only. Contact retrieval requires --fetch-contacts
because the endpoint may consume the account subscription quota.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime, timezone

import httpx

from findly_v1.client import FindlyClient
from findly_v1.config import cfg
from findly_v1.normalizers import normalize
from findly_v1.persistence import create_run, finish_run, get_conn, record_complete_run, save_item, save_phone


def normalize_phone(value: object) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('380') and len(digits) == 12:
        return '+' + digits
    if digits.startswith('0') and len(digits) == 10:
        return '+38' + digits
    return ''


async def collect(operation: str, dry_run: bool, fetch_contacts: bool) -> dict[str, int | bool]:
    source = FindlyClient()
    conn = None if dry_run else get_conn()
    run_id = None if dry_run else create_run(conn, operation)
    started_at = datetime.now(timezone.utc)
    successful_pages = 0
    expected_pages = 0
    parsed = invalid = phones = 0
    error = ''
    try:
        async with httpx.AsyncClient(timeout=cfg.request_timeout, follow_redirects=True) as http:
            auth_status, account = await source.auth(http)
            if auth_status != 200 or not account:
                raise RuntimeError(f'Findly authentication failed (HTTP {auth_status}); refresh FINDLY_COOKIE_FILE')
            status, first = await source.page(http, operation, 1)
            if status != 200 or not first:
                raise RuntimeError(f'Findly {operation} first page failed (HTTP {status})')
            expected_pages = max(1, int((first.get('meta') or {}).get('last_page') or 1))
            pages = [(status, first)]
            for page_number in range(2, expected_pages + 1):
                await asyncio.sleep(cfg.page_delay)
                pages.append(await source.page(http, operation, page_number))
            for status, payload in pages:
                if status != 200 or not payload:
                    continue
                successful_pages += 1
                for item in payload.get('data') or []:
                    if not isinstance(item, dict):
                        continue
                    row = normalize(item, operation)
                    if not row['is_valid']:
                        invalid += 1
                    parsed += 1
                    if not dry_run:
                        save_item(conn, item, row, status)
                    if fetch_contacts and row['is_valid']:

                        contact_status, contact = await source.phone(http, row['external_id'])
                        phone = normalize_phone((contact or {}).get('phone')) if contact_status == 200 else ''
                        if phone and not dry_run:
                            save_phone(conn, row['external_id'], phone)
                            phones += 1
                        await asyncio.sleep(cfg.page_delay)
            completed = expected_pages > 0 and successful_pages == expected_pages
            if not dry_run and completed:
                record_complete_run(conn, operation, started_at)
            return {'parsed': parsed, 'invalid': invalid, 'phones': phones, 'pages': successful_pages, 'expected_pages': expected_pages, 'complete': completed}
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        if conn and run_id:
            finish_run(conn, run_id, expected_pages, successful_pages, error)
            conn.close()


async def main_async(args: argparse.Namespace) -> int:
    operations = ('rent', 'buy') if args.operation == 'all' else (args.operation,)
    for operation in operations:
        report = await collect(operation, args.dry_run, args.fetch_contacts)
        print(f"{operation}: " + ' '.join(f'{key}={value}' for key, value in report.items()))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Isolated Findly collector')
    parser.add_argument('--operation', choices=('rent', 'buy', 'all'), default='all')
    parser.add_argument('--dry-run', action='store_true', help='Read the API but do not write the new database tables.')
    parser.add_argument('--fetch-contacts', action='store_true', help='Explicitly allow the potentially credit-consuming contact endpoint.')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == '__main__':
    main()
