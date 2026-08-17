#!/usr/bin/env python3
"""Backfill only openly published OLX phone links from already stored raw HTML.

Scope is intentionally narrow: apartments in ``active_listings`` with
``source='olx'`` and ``status='active'``.  It performs no HTTP request, browser
automation, proxy use, API call or click on a hidden contact control.  A value
is written only when a publicly rendered ``tel:`` link is present in the raw
HTML captured by the normal parser and ``agent_phone`` is still empty.

Google Sheets are deliberately not written here; the existing locked production
sync remains the sole Sheets writer.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
import psycopg2.extras

from parser_v2.services.process_lock import acquire_process_lock
from parser_v2.utils.phone import normalize_phone


DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin", "connect_timeout": 10}
PUBLIC_TEL_HREF = re.compile(r"<a\\b[^>]*\\bhref\\s*=\\s*['\"]\\s*tel:([^'\"?#<]+)", re.IGNORECASE)


def public_phones(raw_html: str) -> list[str]:
    # Most OLX pages have no public number. Avoid parsing large page bodies
    # unless the literal link scheme exists at all.
    if "tel:" not in raw_html:
        return []
    phones: list[str] = []
    for raw in PUBLIC_TEL_HREF.findall(raw_html):
        phone = normalize_phone(raw)
        digits = re.sub(r"\D", "", phone or "")
        if 10 <= len(digits) <= 15 and phone not in phones:
            phones.append(phone)
    return phones


def candidate_batches(connection, limit: int, batch_size: int):
    """Stream raw pages in small batches; raw HTML is intentionally large."""
    with connection.cursor(name="public_olx_contact_scan", cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.itersize = batch_size
        cursor.execute(
            """
            SELECT listing.id, listing.external_id, listing.url, raw.raw_html
            FROM parser_v2_raw_listings AS raw
            JOIN active_listings AS listing
              ON listing.source = raw.source
             AND listing.external_id = raw.external_id
            WHERE raw.source = 'olx'
              AND raw.parse_status = 'parsed'
              AND raw.http_status = 200
              AND raw.raw_html IS NOT NULL
              AND listing.status = 'active'
              AND listing.property_type = 'Квартира'
              AND COALESCE(listing.agent_phone, '') = ''
            LIMIT %s
            """,
            (limit,),
        )
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [dict(row) for row in rows]


def apply_updates(connection, updates: list[tuple[str, int]]) -> int:
    """Do not overwrite a newer parser value that appeared after selection."""
    with connection.cursor() as cursor:
        for phone, listing_id in updates:
            cursor.execute(
                """
                UPDATE active_listings
                   SET agent_phone = %s,
                       updated_at = NOW()
                 WHERE id = %s
                   AND source = 'olx'
                   AND status = 'active'
                   AND property_type = 'Квартира'
                   AND COALESCE(agent_phone, '') = ''
                """,
                (phone, listing_id),
            )
    connection.commit()
    return len(updates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill publicly rendered OLX contacts from local raw HTML only.")
    parser.add_argument("--limit", type=int, default=5000, help="Maximum eligible raw records to inspect.")
    parser.add_argument("--batch-size", type=int, default=50, help="Raw HTML records held in memory at once.")
    parser.add_argument("--apply", action="store_true", help="Write validated public contacts to active_listings.")
    args = parser.parse_args()
    if args.limit < 1 or args.batch_size < 1 or args.batch_size > 250:
        parser.error("--limit and --batch-size must be positive; batch-size must not exceed 250")

    try:
        acquire_process_lock("backfill_public_olx_contacts")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    connection = psycopg2.connect(**DB)
    write_connection = psycopg2.connect(**DB) if args.apply else None
    try:
        inspected = candidates = updated = 0
        multiple_links = 0
        for rows in candidate_batches(connection, args.limit, args.batch_size):
            inspected += len(rows)
            updates: list[tuple[str, int]] = []
            for row in rows:
                phones = public_phones(row["raw_html"])
                if len(phones) > 1:
                    multiple_links += 1
                if phones:
                    updates.append((phones[0], row["id"]))
            candidates += len(updates)
            if write_connection and updates:
                updated += apply_updates(write_connection, updates)
            if inspected % 1000 == 0:
                print(f"progress inspected={inspected} candidates={candidates} updated={updated}", flush=True)
        print(
            " ".join(
                (
                    f"inspected={inspected}",
                    f"public_phone_candidates={candidates}",
                    f"multiple_public_links={multiple_links}",
                    f"updated={updated}",
                    f"mode={'apply' if args.apply else 'dry-run'}",
                )
            )
        )
        return 0
    finally:
        connection.close()
        if write_connection:
            write_connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
