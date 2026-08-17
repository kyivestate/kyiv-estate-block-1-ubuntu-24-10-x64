"""Backfill only explicitly printed OLX phone numbers from existing source text.

This never opens a hidden-phone control or makes a network request. It accepts
only Ukrainian mobile-shaped values already present in ``title`` or
``description`` and requires ``--apply`` to change source contact fields.
"""
from __future__ import annotations

import argparse
import json
import re

from contact_coverage_v1.refresh import PHONE_PATTERN, get_conn
from parser_v2.utils.phone import normalize_phone


CATALOGS = {
    'apartments': ('active_listings', 'agent_phone'),
    'houses': ('houses_listings', 'agent_phone'),
    'commercial': ('commercial_listings', 'phones'),
}


def extract(text: str) -> list[str]:
    values: list[str] = []
    for raw in re.findall(PHONE_PATTERN, text or ''):
        # PHONE_PATTERN contains a single outer capture; regexp output is a
        # string in Python. Normalization rejects non-Ukrainian lengths.
        phone = normalize_phone(raw)
        digits = re.sub(r'\D', '', phone)
        if (digits.startswith('380') and len(digits) == 12) or (digits.startswith('0') and len(digits) == 10):
            if phone not in values:
                values.append(phone)
    return values


def candidates(cur, catalog: str, table: str, column: str) -> list[tuple[int, list[str]]]:
    empty = "cardinality(COALESCE(phones, ARRAY[]::text[]))=0" if column == 'phones' else "NULLIF(btrim(COALESCE(agent_phone, '')), '') IS NULL"
    cur.execute(f"""
        SELECT id, COALESCE(title, '') || E'\\n' || COALESCE(description, '') AS source_text
          FROM {table}
         WHERE source='olx' AND status='active' AND {empty}
    """)
    result = []
    for listing_id, source_text in cur.fetchall():
        phones = extract(source_text)
        if phones:
            result.append((listing_id, phones))
    return result


def apply(cur, catalog: str, table: str, column: str, rows: list[tuple[int, list[str]]]) -> None:
    for listing_id, phones in rows:
        if column == 'phones':
            cur.execute(f"UPDATE {table} SET phones=%s, contact_visibility='public', updated_at=NOW() WHERE id=%s", (phones, listing_id))
        else:
            cur.execute(f"""UPDATE {table}
                            SET agent_phone=%s,
                                comments=CASE WHEN COALESCE(comments,'')='' THEN 'contact: public phone extracted from OLX text'
                                              ELSE comments || '; contact: public phone extracted from OLX text' END,
                                updated_at=NOW()
                          WHERE id=%s""", (' '.join(phones), listing_id))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write only explicit public-text phones; default is read-only')
    args = parser.parse_args()
    with get_conn() as conn, conn.cursor() as cur:
        planned = {catalog: candidates(cur, catalog, table, column) for catalog, (table, column) in CATALOGS.items()}
        report = {catalog: {'listings': len(rows), 'phone_values': sum(len(phones) for _, phones in rows)} for catalog, rows in planned.items()}
        report['mode'] = 'apply' if args.apply else 'dry-run'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.apply:
            for catalog, (table, column) in CATALOGS.items():
                apply(cur, catalog, table, column, planned[catalog])
            conn.commit()


if __name__ == '__main__':
    main()
