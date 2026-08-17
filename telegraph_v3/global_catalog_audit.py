#!/usr/bin/env python3
"""Read-only catalogue/media audit.

Live source probing is opt-in because it competes with the long-running
coverage crawlers and can trigger Rieltor rate limits.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import psycopg2
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from commercial_v1.parsers import OlxCommercialParser, RieltorCommercialParser
from parser_v2.config import cfg
from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient

DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin"}
CONTOURS = {"apartments": ("active_listings", "Квартира"), "houses": ("houses_listings", "Будинок"), "commercial": ("commercial_listings", None)}


def source_cards(contour: str, source: str, operation: str) -> list[dict]:
    if contour == "commercial":
        parser = OlxCommercialParser(operation, 1) if source == "olx" else RieltorCommercialParser(operation, 1)
    else:
        http = OlxHttpClient(cfg.parser.request_timeout) if source == "olx" else RieltorHttpClient(cfg.parser.request_timeout)
        prop = {CONTOURS[contour][1]}
        parser = OlxParser(http, operation, 1, prop) if source == "olx" else RieltorParser(http, operation, 1, prop, geographic_scope="kyiv_region")
    try:
        return parser.collect_listing_urls()[:20]
    finally:
        # Apartment/house parsers receive a shared HTTP client and do not own
        # a ``close`` method; commercial parsers do.  Close whichever exists.
        closer = getattr(parser, "close", None) or getattr(parser, "http", None).close
        closer()


def catalogue_audit(conn) -> dict:
    report, candidates = {}, []
    with conn.cursor() as cur:
        for contour, (table, _) in CONTOURS.items():
            for source in ("olx", "rieltor"):
                for operation in ("rent", "buy"):
                    key = f"{contour}:{source}:{operation}"
                    try:
                        cards = source_cards(contour, source, operation)
                    except Exception as error:
                        report[key] = {"error": str(error)[:300]}
                        continue
                    ids = [card["external_id"] for card in cards]
                    cur.execute(f"SELECT external_id,status FROM {table} WHERE source=%s AND operation=%s AND external_id=ANY(%s)", (source, operation, ids))
                    states = dict(cur.fetchall())
                    counts = Counter(states.get(ext, "missing") for ext in ids)
                    report[key] = {"source_cards": len(ids), **dict(counts), "missing_ids": [ext for ext in ids if ext not in states]}
                    candidates.extend((contour, source, operation, card) for card in cards if states.get(card["external_id"]) != "active")
    return {"groups": report, "non_active_source_cards": candidates}


def image_nodes(nodes) -> list[str]:
    found = []
    for node in nodes or []:
        if isinstance(node, dict):
            if node.get("tag") == "img" and isinstance(node.get("attrs", {}).get("src"), str):
                found.append(node["attrs"]["src"])
            found.extend(image_nodes(node.get("children")))
    return found


def telegraph_audit(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.catalog,p.listing_id,p.ua_url,p.en_url,
              CASE p.catalog WHEN 'apartments' THEN a.photos WHEN 'houses' THEN h.photos ELSE c.photos END
            FROM block3.publications p
            LEFT JOIN active_listings a ON p.catalog='apartments' AND a.id=p.listing_id
            LEFT JOIN houses_listings h ON p.catalog='houses' AND h.id=p.listing_id
            LEFT JOIN commercial_listings c ON p.catalog='commercial' AND c.id=p.listing_id
            WHERE p.status='published'
            ORDER BY p.catalog,p.listing_id
        """)
        rows = cur.fetchall()
    session = requests.Session()
    failures, image_shortfall, checked = [], [], 0
    for catalog, listing_id, ua_url, en_url, photos in rows:
        expected = len(photos or [])
        for locale, url in (("ua", ua_url), ("en", en_url)):
            checked += 1
            try:
                response = session.get(url, timeout=25)
                response.raise_for_status()
                # Telegraph keeps image addresses in the rendered HTML.
                actual = response.text.count('<img')
                if actual < expected:
                    image_shortfall.append({"catalog": catalog, "listing_id": listing_id, "locale": locale, "expected": expected, "actual": actual})
            except Exception as error:
                failures.append({"catalog": catalog, "listing_id": listing_id, "locale": locale, "error": str(error)[:180]})
    return {"pages_checked": checked, "page_failures": failures, "photo_shortfall": image_shortfall}


def main() -> None:
    import argparse
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--skip-telegraph", action="store_true")
    args.add_argument(
        "--live-sources",
        action="store_true",
        help="probe source page cards (only run when no full crawler is active)",
    )
    options = args.parse_args()
    with psycopg2.connect(**DB) as conn:
        catalogues = catalogue_audit(conn) if options.live_sources else {
            "skipped": True,
            "reason": "live source probes are disabled by default to avoid rate-limit contention",
        }
        telegraph = {"skipped": True} if options.skip_telegraph else telegraph_audit(conn)
    print(json.dumps({"catalogues": catalogues, "telegraph": telegraph}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
