"""Database writes for Findly only; no legacy table names appear here."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2.extras import Json

from parser_v2.config import cfg as app_cfg


def get_conn():
    return psycopg2.connect(host=app_cfg.db.host, port=app_cfg.db.port, dbname=app_cfg.db.dbname, user=app_cfg.db.user, password=app_cfg.db.password or None)


def create_run(conn, operation: str) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO findly_collection_runs(operation) VALUES (%s) RETURNING id", (operation,))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn, run_id: int, expected_pages: int, successful_pages: int, error: str = '') -> bool:
    complete = expected_pages > 0 and successful_pages == expected_pages
    with conn.cursor() as cur:
        cur.execute("UPDATE findly_collection_runs SET completed_at=NOW(), expected_pages=%s, successful_pages=%s, status=%s, error_message=%s WHERE id=%s",
                    (expected_pages, successful_pages, 'completed' if complete else 'failed', error[:1000], run_id))
    conn.commit()
    return complete


def save_item(conn, item: dict[str, Any], normalized: dict[str, Any], http_status: int = 200) -> None:
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    content_hash = hashlib.sha256(payload.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO findly_raw_listings(source,operation,external_id,url,http_status,raw_json,content_hash,parse_status)
            VALUES ('findly',%s,%s,%s,%s,%s,%s,'parsed')
            ON CONFLICT (source,external_id) DO UPDATE SET operation=EXCLUDED.operation,url=EXCLUDED.url,fetched_at=NOW(),http_status=EXCLUDED.http_status,
              raw_json=EXCLUDED.raw_json,content_hash=EXCLUDED.content_hash,parse_status='parsed',error_message='',updated_at=NOW() RETURNING id""",
            (normalized['operation'], normalized['external_id'], normalized['url'], http_status, Json(item), content_hash))
        raw_id = cur.fetchone()[0]
        keys = ('operation','external_id','origin_source','url','title','description','property_type','price_uah','price_usd','price_eur','source_price_raw','source_currency','rooms','area','floor','floors_total','district','city','street','full_address','latitude','longitude','photo_url','photos','contact_name','contact_phone','commission','extraction_confidence','is_valid','validation_errors')
        values = [normalized[key] for key in keys]
        cur.execute("""INSERT INTO findly_normalized_listings(source,operation,external_id,origin_source,url,title,description,property_type,price_uah,price_usd,price_eur,source_price_raw,source_currency,rooms,area,floor,floors_total,district,city,street,full_address,latitude,longitude,photo_url,photos,contact_name,contact_phone,commission,extraction_confidence,is_valid,validation_errors,raw_listing_id,parsed_at)
            VALUES ('findly',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (source,external_id) DO UPDATE SET operation=EXCLUDED.operation,origin_source=EXCLUDED.origin_source,url=EXCLUDED.url,title=EXCLUDED.title,description=EXCLUDED.description,property_type=EXCLUDED.property_type,price_uah=EXCLUDED.price_uah,price_usd=EXCLUDED.price_usd,price_eur=EXCLUDED.price_eur,source_price_raw=EXCLUDED.source_price_raw,source_currency=EXCLUDED.source_currency,rooms=EXCLUDED.rooms,area=EXCLUDED.area,floor=EXCLUDED.floor,floors_total=EXCLUDED.floors_total,district=EXCLUDED.district,city=EXCLUDED.city,street=EXCLUDED.street,full_address=EXCLUDED.full_address,latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,photo_url=EXCLUDED.photo_url,photos=EXCLUDED.photos,contact_name=EXCLUDED.contact_name,contact_phone=EXCLUDED.contact_phone,commission=EXCLUDED.commission,extraction_confidence=EXCLUDED.extraction_confidence,is_valid=EXCLUDED.is_valid,validation_errors=EXCLUDED.validation_errors,raw_listing_id=EXCLUDED.raw_listing_id,parsed_at=NOW(),updated_at=NOW()""",
            (*values[:-3], Json(values[-3]), values[-2], values[-1], raw_id))
        if normalized['is_valid']:
            cur.execute("""INSERT INTO findly_listings(source,external_id,operation,origin_source,url,title,description,property_type,price_uah,price_usd,price_eur,rooms,area,floor,floors_total,district,city,street,full_address,latitude,longitude,photo_url,photos,contact_name,contact_phone,commission,status,last_seen_at,parsed_at,data_completeness)
                VALUES ('findly',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',NOW(),NOW(),%s)
                ON CONFLICT (source,external_id) DO UPDATE SET operation=EXCLUDED.operation,origin_source=EXCLUDED.origin_source,url=EXCLUDED.url,title=EXCLUDED.title,description=EXCLUDED.description,property_type=EXCLUDED.property_type,price_uah=EXCLUDED.price_uah,price_usd=EXCLUDED.price_usd,price_eur=EXCLUDED.price_eur,rooms=EXCLUDED.rooms,area=EXCLUDED.area,floor=EXCLUDED.floor,floors_total=EXCLUDED.floors_total,district=EXCLUDED.district,city=EXCLUDED.city,street=EXCLUDED.street,full_address=EXCLUDED.full_address,latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,photo_url=EXCLUDED.photo_url,photos=EXCLUDED.photos,contact_name=EXCLUDED.contact_name,contact_phone=COALESCE(NULLIF(EXCLUDED.contact_phone,''),findly_listings.contact_phone),commission=EXCLUDED.commission,status=CASE WHEN findly_listings.status IN ('quarantine','archived') THEN findly_listings.status ELSE 'active' END,last_seen_at=NOW(),parsed_at=NOW(),updated_at=NOW(),data_completeness=EXCLUDED.data_completeness""",
                (normalized['external_id'], normalized['operation'], normalized['origin_source'], normalized['url'], normalized['title'], normalized['description'], normalized['property_type'], normalized['price_uah'], normalized['price_usd'], normalized['price_eur'], normalized['rooms'], normalized['area'], normalized['floor'], normalized['floors_total'], normalized['district'], normalized['city'], normalized['street'], normalized['full_address'], normalized['latitude'], normalized['longitude'], normalized['photo_url'], normalized['photos'], normalized['contact_name'], normalized['contact_phone'], normalized['commission'], _completeness(normalized)))
    conn.commit()


def _completeness(row: dict[str, Any]) -> int:
    fields = ('title','description','price_uah','price_usd','price_eur','area','district','city','photo_url')
    return round(sum(bool(row.get(key)) for key in fields) * 100 / len(fields))


def save_phone(conn, external_id: str, phone: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE findly_listings SET contact_phone=%s, updated_at=NOW() WHERE source='findly' AND external_id=%s", (phone, external_id))
    conn.commit()


def record_complete_run(conn, operation: str, started_at: datetime) -> int:
    """Require two complete successful listings before declaring an item inactive."""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO findly_listing_status_checks(listing_id,checked_at,missing_complete_runs,last_seen_at,note)
            SELECT id,NOW(),0,last_seen_at,'seen in complete collection' FROM findly_listings WHERE operation=%s AND status='active' AND last_seen_at >= %s
            ON CONFLICT (listing_id) DO UPDATE SET checked_at=EXCLUDED.checked_at,missing_complete_runs=0,last_seen_at=EXCLUDED.last_seen_at,note=EXCLUDED.note""", (operation, started_at))
        cur.execute("""UPDATE findly_listing_status_checks checks SET checked_at=NOW(),missing_complete_runs=checks.missing_complete_runs+1,note='absent from complete collection'
            FROM findly_listings listing WHERE checks.listing_id=listing.id AND listing.operation=%s AND listing.status='active' AND listing.last_seen_at < %s""", (operation, started_at))
        cur.execute("""UPDATE findly_listings listing SET status='inactive',updated_at=NOW(),comments=CASE WHEN comments='' THEN 'inactive after two complete Findly collections' ELSE comments || '; inactive after two complete Findly collections' END
            FROM findly_listing_status_checks checks WHERE checks.listing_id=listing.id AND checks.missing_complete_runs >= 2 AND listing.status='active'""")
        changed = cur.rowcount
    conn.commit()
    return changed
