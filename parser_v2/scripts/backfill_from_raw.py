import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
import psycopg2.extras

from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.address_parser import parse_address
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.process_lock import acquire_process_lock
from parser_v2.services.photo_selection import select_property_photo, select_property_photos
from parser_v2.utils.phone import normalize_phone
from parser_v2.utils.text import clean_text, extract_int


DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin"}


def missing(value):
    return value is None or not str(value).strip()


def number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").replace("м²", "").strip())
    except ValueError:
        return None


def needs_backfill(row):
    core = ("rooms", "area", "district", "street", "metro_station", "photo_url", "description")
    if any(missing(row.get(field)) for field in core):
        return True
    if row["property_type"] == "Квартира" and (row.get("floor") is None or row.get("floors_total") is None):
        return True
    if row["property_type"] == "Будинок" and row.get("floors_total") is None:
        return True
    if row["source"] == "rieltor" and (missing(row.get("agent_name")) or missing(row.get("agent_phone"))):
        return True
    return False


def values_from_source(row, source):
    address = parse_address(
        clean_text(source.get("address", "")),
        clean_text(source.get("district", "")),
        clean_text(source.get("street", "")),
        clean_text(source.get("residential_complex", "")),
    )
    candidates = {
        "title": clean_text(source.get("title", ""))[:500],
        "description": clean_text(source.get("description", ""))[:49000],
        "rooms": extract_int(str(source.get("rooms", ""))) if source.get("rooms") else None,
        "area": number(source.get("area")),
        "floor": extract_int(str(source.get("floor", ""))) if source.get("floor") else None,
        "floors_total": extract_int(str(source.get("floors_total", ""))) if source.get("floors_total") else None,
        "district": address["district"],
        "street": address["street"],
        "residential_complex": address["residential_complex"],
        "metro_station": clean_text(source.get("metro_station", ""))[:100],
        "agent_type": clean_text(source.get("agent_type", "")),
        "agent_name": clean_text(source.get("contact_name", ""))[:200],
        "agent_phone": normalize_phone(source.get("contact_phone", ""))[:50],
        "commission": clean_text(source.get("commission", ""))[:100],
    }
    photos = select_property_photos(source.get("photos", []), source.get("photo_url", ""))[:20]
    candidates["photo_url"] = select_property_photo(photos, source.get("photo_url", ""))
    candidates["photos"] = photos
    return candidates


def updates_for(row, candidates):
    updates = {}
    for field in ("title", "rooms", "area", "district", "street", "residential_complex", "metro_station", "agent_name", "agent_phone", "commission", "photo_url"):
        if missing(row.get(field)) and candidates.get(field) not in (None, ""):
            updates[field] = candidates[field]
    if missing(row.get("description")) or len(str(row.get("description") or "").strip()) < 40:
        if candidates.get("description") and len(candidates["description"]) >= 40:
            updates["description"] = candidates["description"]
    if row["property_type"] == "Квартира":
        for field in ("floor", "floors_total"):
            if row.get(field) is None and candidates.get(field) is not None:
                updates[field] = candidates[field]
    elif row["property_type"] == "Будинок" and row.get("floors_total") is None and candidates.get("floors_total") is not None:
        updates["floors_total"] = candidates["floors_total"]
    if missing(row.get("agent_type")) or row.get("agent_type") in {"unknown", "Не вказано"}:
        if candidates.get("agent_type") in {"owner", "agent", "agency"}:
            updates["agent_type"] = candidates["agent_type"]
    if not row.get("photos") and candidates.get("photos"):
        updates["photos"] = candidates["photos"]
    return updates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=250)
    args = parser.parse_args()
    if args.workers < 1 or args.worker < 0 or args.worker >= args.workers:
        raise SystemExit("invalid worker partition")
    try:
        acquire_process_lock(f"backfill_raw_{args.worker}")
    except RuntimeError:
        print(f"worker={args.worker} already_running")
        return
    conn = psycopg2.connect(**DB)
    olx_http = OlxHttpClient()
    rieltor_http = RieltorHttpClient()
    parsers = {
        "olx": OlxParser(olx_http, "buy"),
        "rieltor": RieltorParser(rieltor_http, "buy"),
    }
    stats = {"rows": 0, "updated": 0, "fields": 0, "failed": 0}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as read, conn.cursor() as write:
            write.execute("""CREATE TABLE IF NOT EXISTS listing_enrichment_attempts (
                listing_id BIGINT PRIMARY KEY REFERENCES active_listings(id),
                raw_checked_at TIMESTAMPTZ NOT NULL
            )""")
            conn.commit()
            read.execute("""SELECT listing.id, listing.source, listing.operation, listing.property_type, listing.url,
                listing.title, listing.description, listing.rooms, listing.area, listing.floor, listing.floors_total,
                listing.district, listing.street, listing.residential_complex, listing.metro_station,
                listing.agent_type, listing.agent_name, listing.agent_phone, listing.commission,
                listing.photo_url, listing.photos, raw.raw_html
                FROM active_listings listing
                JOIN parser_v2_raw_listings raw ON raw.source=listing.source AND raw.external_id=listing.external_id
                LEFT JOIN listing_enrichment_attempts attempt ON attempt.listing_id=listing.id
                WHERE listing.status='active' AND listing.source IN ('olx','rieltor')
                  AND raw.raw_html IS NOT NULL AND length(raw.raw_html)>500
                  AND (attempt.raw_checked_at IS NULL OR attempt.raw_checked_at < NOW() - INTERVAL '14 days')
                  AND listing.id %% %s = %s
                ORDER BY listing.updated_at ASC NULLS FIRST
                LIMIT %s""", (args.workers, args.worker, args.limit))
            rows = read.fetchall()
            for row in rows:
                stats["rows"] += 1
                if needs_backfill(row):
                    try:
                        extracted = parsers[row["source"]]._extract(row["raw_html"], row["url"])
                        updates = updates_for(row, values_from_source(row, extracted))
                        if updates:
                            columns = ", ".join(f"{field}=%s" for field in updates)
                            write.execute(f"UPDATE active_listings SET {columns}, updated_at=NOW() WHERE id=%s", [*updates.values(), row["id"]])
                            stats["updated"] += 1
                            stats["fields"] += len(updates)
                    except Exception:
                        stats["failed"] += 1
                write.execute("""INSERT INTO listing_enrichment_attempts (listing_id, raw_checked_at)
                    VALUES (%s, NOW())
                    ON CONFLICT (listing_id) DO UPDATE SET raw_checked_at=EXCLUDED.raw_checked_at""", (row["id"],))
                if stats["rows"] % 100 == 0:
                    conn.commit()
            conn.commit()
    finally:
        olx_http.close()
        rieltor_http.close()
        conn.close()
    print(" ".join(f"{key}={value}" for key, value in stats.items()))


if __name__ == "__main__":
    main()
