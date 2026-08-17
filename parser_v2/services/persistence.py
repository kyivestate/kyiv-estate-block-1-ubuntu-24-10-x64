from __future__ import annotations

import json
from datetime import datetime

import psycopg2

from parser_v2.config import cfg
from parser_v2.models.listing import RawListing, NormalizedListing
from parser_v2.services.logging_setup import get_logger


log = get_logger("persistence")


def get_conn():
    return psycopg2.connect(
        host=cfg.db.host,
        port=cfg.db.port,
        dbname=cfg.db.dbname,
        user=cfg.db.user,
        password=cfg.db.password or None,
    )


def save_raw_listing(conn, raw: RawListing) -> int:
    sql = """INSERT INTO parser_v2_raw_listings
        (source,operation,external_id,url,fetched_at,http_status,raw_html,raw_json,content_hash,parse_status,error_message,retry_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source,external_id) DO UPDATE SET
            url=EXCLUDED.url, fetched_at=EXCLUDED.fetched_at, http_status=EXCLUDED.http_status,
            raw_html=EXCLUDED.raw_html, content_hash=EXCLUDED.content_hash,
            parse_status=EXCLUDED.parse_status, error_message=EXCLUDED.error_message,
            retry_count=parser_v2_raw_listings.retry_count+1, updated_at=NOW()
        RETURNING id"""
    with conn.cursor() as cur:
        cur.execute(sql, (raw.source, raw.operation, raw.external_id, raw.url, raw.fetched_at, raw.http_status,
            raw.raw_html, raw.raw_json, raw.content_hash, raw.parse_status, raw.error_message, raw.retry_count))
        row = cur.fetchone()
        return row[0] if row else 0


def save_normalized_listing(conn, nl: NormalizedListing) -> int:
    sql = """INSERT INTO parser_v2_normalized_listings
        (source,operation,external_id,url,property_type,title,description,
         price_uah,price_usd,price_eur,source_price_raw,source_currency,
         rooms,area,floor,floor_total,agent_type,contact_name,contact_phone,
         commission,residential_complex,city,district,street,metro_station,full_address,
         photo_url,photos,cdn_photo_url,cdn_photos,sheet_image_formula,
         extraction_confidence,is_valid,validation_errors,raw_listing_id,parsed_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source,external_id) DO UPDATE SET
            url=EXCLUDED.url,property_type=EXCLUDED.property_type,title=EXCLUDED.title,description=EXCLUDED.description,
            price_uah=EXCLUDED.price_uah,price_usd=EXCLUDED.price_usd,price_eur=EXCLUDED.price_eur,
            source_price_raw=EXCLUDED.source_price_raw,source_currency=EXCLUDED.source_currency,
            rooms=EXCLUDED.rooms,area=EXCLUDED.area,floor=EXCLUDED.floor,floor_total=EXCLUDED.floor_total,
            agent_type=EXCLUDED.agent_type,contact_name=EXCLUDED.contact_name,contact_phone=EXCLUDED.contact_phone,
            commission=EXCLUDED.commission,residential_complex=EXCLUDED.residential_complex,
            city=EXCLUDED.city,district=EXCLUDED.district,street=EXCLUDED.street,metro_station=EXCLUDED.metro_station,full_address=EXCLUDED.full_address,
            photo_url=EXCLUDED.photo_url,photos=EXCLUDED.photos,cdn_photo_url=EXCLUDED.cdn_photo_url,
            cdn_photos=EXCLUDED.cdn_photos,sheet_image_formula=EXCLUDED.sheet_image_formula,
            extraction_confidence=EXCLUDED.extraction_confidence,is_valid=EXCLUDED.is_valid,
            validation_errors=EXCLUDED.validation_errors,raw_listing_id=EXCLUDED.raw_listing_id,
            parsed_at=EXCLUDED.parsed_at,updated_at=NOW()
        RETURNING id"""
    with conn.cursor() as cur:
        cur.execute(sql, (nl.source, nl.operation, nl.external_id, nl.url, nl.property_type, nl.title, nl.description,
            nl.price_uah, nl.price_usd, nl.price_eur, nl.source_price_raw, nl.source_currency,
            nl.rooms, nl.area, nl.floor, nl.floor_total, nl.agent_type, nl.contact_name, nl.contact_phone,
            nl.commission, nl.residential_complex, nl.city, nl.district, nl.street, nl.metro_station, nl.full_address,
            nl.photo_url, nl.photos, nl.cdn_photo_url, nl.cdn_photos, nl.sheet_image_formula,
            json.dumps(nl.extraction_confidence, ensure_ascii=False), nl.is_valid, nl.validation_errors,
            nl.raw_listing_id, nl.parsed_at))
        row = cur.fetchone()
        return row[0] if row else 0


def merge_v2_into_active(conn, source_filter: str = "olx,rieltor", since: datetime | None = None) -> int:
    sources = [source.strip() for source in source_filter.split(",") if source.strip()]
    if not sources:
        return 0
    placeholders = ",".join(["%s"] * len(sources))
    conditions = ["n.is_valid = true", "n.property_type = 'Квартира'", f"n.source IN ({placeholders})"]
    params = list(sources)
    if since is not None:
        conditions.append("n.updated_at >= %s")
        params.append(since)
    sql = f"""INSERT INTO active_listings
        (external_id, source, operation, property_type, title, description,
         price_uah, price_usd, price_eur,
         area, floor, floors_total, rooms,
         district, city, street, metro_station, residential_complex, commission,
         url, photo_url, photos,
         agent_type, agent_name, agent_phone,
         status, created_at, updated_at, parsed_at)
    SELECT
        n.external_id, n.source, n.operation, n.property_type, n.title, n.description,
        n.price_uah, n.price_usd, n.price_eur,
        n.area, n.floor, n.floor_total, n.rooms,
        n.district, n.city, n.street, n.metro_station, n.residential_complex, n.commission,
        n.url,
        COALESCE(n.cdn_photo_url, n.photo_url),
        COALESCE(n.cdn_photos, n.photos),
        n.agent_type, n.contact_name, n.contact_phone,
        'active', NOW(), NOW(), n.parsed_at
    FROM parser_v2_normalized_listings n
    WHERE {' AND '.join(conditions)}
    ON CONFLICT (source, external_id) DO UPDATE SET
        operation = EXCLUDED.operation,
        property_type = COALESCE(NULLIF(EXCLUDED.property_type, ''), active_listings.property_type),
        title = COALESCE(NULLIF(EXCLUDED.title, ''), active_listings.title),
        description = COALESCE(NULLIF(EXCLUDED.description, ''), active_listings.description),
        price_uah = COALESCE(EXCLUDED.price_uah, active_listings.price_uah),
        price_usd = COALESCE(EXCLUDED.price_usd, active_listings.price_usd),
        price_eur = COALESCE(EXCLUDED.price_eur, active_listings.price_eur),
        area = COALESCE(EXCLUDED.area, active_listings.area),
        floor = COALESCE(EXCLUDED.floor, active_listings.floor),
        floors_total = COALESCE(EXCLUDED.floors_total, active_listings.floors_total),
        rooms = COALESCE(EXCLUDED.rooms, active_listings.rooms),
        district = COALESCE(NULLIF(EXCLUDED.district, ''), active_listings.district),
        city = COALESCE(NULLIF(EXCLUDED.city, ''), active_listings.city),
        street = COALESCE(NULLIF(EXCLUDED.street, ''), active_listings.street),
        metro_station = COALESCE(NULLIF(EXCLUDED.metro_station, ''), active_listings.metro_station),
        residential_complex = COALESCE(NULLIF(EXCLUDED.residential_complex, ''), active_listings.residential_complex),
        commission = COALESCE(NULLIF(EXCLUDED.commission, ''), active_listings.commission),
        url = EXCLUDED.url,
        photo_url = COALESCE(NULLIF(EXCLUDED.photo_url, ''), active_listings.photo_url),
        photos = CASE WHEN EXCLUDED.photos IS NOT NULL AND array_length(EXCLUDED.photos, 1) > 0
                      THEN EXCLUDED.photos ELSE active_listings.photos END,
        agent_type = COALESCE(NULLIF(EXCLUDED.agent_type, 'unknown'), active_listings.agent_type),
        agent_name = COALESCE(NULLIF(EXCLUDED.agent_name, ''), active_listings.agent_name),
        agent_phone = COALESCE(NULLIF(EXCLUDED.agent_phone, ''), active_listings.agent_phone),
        status = CASE WHEN active_listings.status IN ('quarantine', 'archived')
                      THEN active_listings.status ELSE 'active' END,
        updated_at = NOW(),
        parsed_at = EXCLUDED.parsed_at
    WHERE active_listings.source NOT IN ('findly', 'findly_olx', 'findly_rieltor')"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        merged = cur.rowcount
    conn.commit()
    log.info("Merged %d fresh rows into active_listings", merged)
    return merged


def get_existing_external_ids(conn, source: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT external_id FROM active_listings WHERE source=%s AND status='active'", (source,))
        return {row[0] for row in cur.fetchall() if row[0]}
