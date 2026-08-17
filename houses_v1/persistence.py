from __future__ import annotations

import json
from datetime import datetime
import psycopg2
from parser_v2.config import cfg
from parser_v2.models.listing import RawListing, NormalizedListing


def get_conn():
    return psycopg2.connect(host=cfg.db.host, port=cfg.db.port, dbname=cfg.db.dbname, user=cfg.db.user, password=cfg.db.password or None)


def existing_external_ids(conn, source: str, operation: str) -> set[str]:
    """Existing production houses are immutable to intake-policy changes."""
    with conn.cursor() as cur:
        cur.execute("SELECT external_id FROM houses_listings WHERE source=%s AND operation=%s", (source, operation))
        return {row[0] for row in cur.fetchall()}


def save_raw_listing(conn, raw: RawListing) -> int:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO houses_raw_listings
            (source,operation,external_id,url,fetched_at,http_status,raw_html,raw_json,content_hash,parse_status,error_message,retry_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source,external_id) DO UPDATE SET url=EXCLUDED.url,fetched_at=EXCLUDED.fetched_at,http_status=EXCLUDED.http_status,
              raw_html=EXCLUDED.raw_html,raw_json=EXCLUDED.raw_json,content_hash=EXCLUDED.content_hash,parse_status=EXCLUDED.parse_status,
              error_message=EXCLUDED.error_message,retry_count=houses_raw_listings.retry_count+1,updated_at=NOW() RETURNING id""",
            (raw.source, raw.operation, raw.external_id, raw.url, raw.fetched_at, raw.http_status, raw.raw_html, raw.raw_json,
             raw.content_hash, raw.parse_status, raw.error_message, raw.retry_count))
        return cur.fetchone()[0]


def save_normalized_listing(conn, listing: NormalizedListing) -> int:
    if listing.property_type != 'Будинок':
        raise ValueError('houses contour accepts only property_type=Будинок')
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO houses_normalized_listings
          (source,operation,external_id,url,property_type,title,description,price_uah,price_usd,price_eur,source_price_raw,source_currency,
           rooms,area,floor,floor_total,agent_type,contact_name,contact_phone,commission,residential_complex,city,district,street,metro_station,
           full_address,photo_url,photos,extraction_confidence,is_valid,validation_errors,raw_listing_id,parsed_at)
          VALUES (%s,%s,%s,%s,'Будинок',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT (source,external_id) DO UPDATE SET url=EXCLUDED.url,title=EXCLUDED.title,description=EXCLUDED.description,
           price_uah=EXCLUDED.price_uah,price_usd=EXCLUDED.price_usd,price_eur=EXCLUDED.price_eur,source_price_raw=EXCLUDED.source_price_raw,
           source_currency=EXCLUDED.source_currency,rooms=EXCLUDED.rooms,area=EXCLUDED.area,floor=EXCLUDED.floor,floor_total=EXCLUDED.floor_total,
           agent_type=EXCLUDED.agent_type,contact_name=EXCLUDED.contact_name,contact_phone=EXCLUDED.contact_phone,commission=EXCLUDED.commission,
           residential_complex=EXCLUDED.residential_complex,city=EXCLUDED.city,district=EXCLUDED.district,street=EXCLUDED.street,
           metro_station=EXCLUDED.metro_station,full_address=EXCLUDED.full_address,photo_url=EXCLUDED.photo_url,photos=EXCLUDED.photos,
           extraction_confidence=EXCLUDED.extraction_confidence,is_valid=EXCLUDED.is_valid,validation_errors=EXCLUDED.validation_errors,
           raw_listing_id=EXCLUDED.raw_listing_id,parsed_at=EXCLUDED.parsed_at,updated_at=NOW() RETURNING id""",
          (listing.source,listing.operation,listing.external_id,listing.url,listing.title,listing.description,listing.price_uah,listing.price_usd,
           listing.price_eur,listing.source_price_raw,listing.source_currency,listing.rooms,listing.area,listing.floor,listing.floor_total,
           listing.agent_type,listing.contact_name,listing.contact_phone,listing.commission,listing.residential_complex,listing.city,listing.district,
           listing.street,listing.metro_station,listing.full_address,listing.photo_url,listing.photos,json.dumps(listing.extraction_confidence,ensure_ascii=False),
           listing.is_valid,listing.validation_errors,listing.raw_listing_id,listing.parsed_at))
        return cur.fetchone()[0]


def merge_into_houses(conn, since: datetime | None = None) -> int:
    with conn.cursor() as cur:
        query = """INSERT INTO houses_listings
          (external_id,source,operation,property_type,title,description,price_uah,price_usd,price_eur,area,floor,floors_total,rooms,district,city,
           street,metro_station,residential_complex,commission,url,photo_url,photos,agent_type,agent_name,agent_phone,status,parsed_at,updated_at)
          SELECT external_id,source,operation,'Будинок',title,description,price_uah,price_usd,price_eur,area,floor,floor_total,rooms,district,city,
           street,metro_station,residential_complex,commission,url,photo_url,photos,agent_type,contact_name,contact_phone,'active',parsed_at,NOW()
          FROM houses_normalized_listings WHERE is_valid=true
          ON CONFLICT (source,external_id) DO UPDATE SET operation=EXCLUDED.operation,title=EXCLUDED.title,description=EXCLUDED.description,
           price_uah=EXCLUDED.price_uah,price_usd=EXCLUDED.price_usd,price_eur=EXCLUDED.price_eur,area=EXCLUDED.area,floor=EXCLUDED.floor,
           floors_total=EXCLUDED.floors_total,rooms=EXCLUDED.rooms,district=EXCLUDED.district,city=EXCLUDED.city,street=EXCLUDED.street,
           metro_station=EXCLUDED.metro_station,residential_complex=EXCLUDED.residential_complex,commission=EXCLUDED.commission,url=EXCLUDED.url,
           photo_url=EXCLUDED.photo_url,photos=EXCLUDED.photos,agent_type=EXCLUDED.agent_type,agent_name=EXCLUDED.agent_name,
           agent_phone=COALESCE(NULLIF(EXCLUDED.agent_phone,''),houses_listings.agent_phone),
           status=CASE WHEN houses_listings.status IN ('quarantine','archived') THEN houses_listings.status ELSE 'active' END,
           parsed_at=EXCLUDED.parsed_at,updated_at=NOW()"""
        params: tuple[object, ...] = ()
        if since is not None:
            query = query.replace("FROM houses_normalized_listings WHERE is_valid=true", "FROM houses_normalized_listings WHERE is_valid=true AND updated_at >= %s")
            params = (since,)
        cur.execute(query, params)
        count = cur.rowcount
    conn.commit()
    return count


def clear_invalid_floor_pairs(conn) -> int:
    """Never infer floor information: remove only contradictory source values."""
    with conn.cursor() as cur:
        cur.execute("""UPDATE houses_listings
            SET floor=NULL, floors_total=NULL,
                comments=CASE WHEN COALESCE(comments,'')='' THEN 'quality: invalid floor values cleared'
                              ELSE comments || '; quality: invalid floor values cleared' END,
                updated_at=NOW()
            WHERE floor IS NOT NULL AND floors_total IS NOT NULL AND floor > floors_total""")
        count = cur.rowcount
    conn.commit()
    return count
