from __future__ import annotations

import json

import psycopg2

from commercial_v1.config import cfg
from commercial_v1.models import CommercialListing, CommercialRawListing


def get_connection():
    return psycopg2.connect(
        host=cfg.db_host,
        port=cfg.db_port,
        dbname=cfg.db_name,
        user=cfg.db_user,
        password=cfg.db_password or None,
    )


def save_raw(connection, raw: CommercialRawListing) -> int:
    sql = """
        INSERT INTO commercial_raw_listings
        (source, operation, external_id, url, fetched_at, http_status, raw_html, content_hash, parse_status, error_message)
        VALUES (%(source)s, %(operation)s, %(external_id)s, %(url)s, %(fetched_at)s, %(http_status)s, %(raw_html)s, %(content_hash)s, %(parse_status)s, %(error_message)s)
        ON CONFLICT (source, external_id) DO UPDATE SET
            operation=EXCLUDED.operation, url=EXCLUDED.url, fetched_at=EXCLUDED.fetched_at,
            http_status=EXCLUDED.http_status, raw_html=EXCLUDED.raw_html, content_hash=EXCLUDED.content_hash,
            parse_status=EXCLUDED.parse_status, error_message=EXCLUDED.error_message, updated_at=NOW()
        RETURNING id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, raw.__dict__)
        return cursor.fetchone()[0]


LISTING_COLUMNS = (
    "source", "external_id", "operation", "url", "commercial_type", "commercial_subtype", "title", "description", "ai_title", "ai_description",
    "price_amount", "price_currency", "price_period", "price_uah", "price_usd", "price_eur", "price_per_m2", "price_per_m2_currency", "price_per_m2_uah", "price_per_m2_usd", "price_per_m2_eur", "price_per_m2_period", "source_price_raw",
    "vat_included", "opex_amount", "utilities_included", "area_total_m2", "area_usable_m2", "floor", "floors_total",
    "floor_label", "ceiling_height_m", "layout_type", "condition", "fitout", "separate_entrance", "facade",
    "showcase_windows", "parking_spaces", "loading_dock", "ramp", "freight_elevator", "electric_power_kw",
    "electricity_backup", "generator", "water_supply", "sewerage", "heating_type", "ventilation", "air_conditioning",
    "fire_safety", "security", "internet", "shelter_distance_m", "permitted_use", "city", "district", "street",
    "full_address", "address_confidence", "advertiser_type", "contact_name", "agency_name", "phones", "commission_text",
    "contact_visibility", "photo_url", "photos", "extraction_confidence", "validation_errors", "raw_listing_id", "parsed_at",
)
TEXT_COLUMNS = {
    "commercial_subtype", "title", "description", "ai_title", "ai_description", "price_currency", "price_period", "price_per_m2_currency", "price_per_m2_period", "source_price_raw",
    "floor_label", "layout_type", "condition", "fitout", "heating_type", "permitted_use", "district", "street",
    "full_address", "address_confidence", "advertiser_type", "contact_name", "agency_name", "commission_text",
    "contact_visibility", "photo_url",
}


def save_listing(connection, listing: CommercialListing) -> int:
    values = dict(listing.__dict__)
    values["extraction_confidence"] = json.dumps(values["extraction_confidence"], ensure_ascii=False)
    columns = ", ".join(LISTING_COLUMNS)
    placeholders = ", ".join(f"%({column})s" for column in LISTING_COLUMNS)
    updates: list[str] = ["operation=EXCLUDED.operation", "url=EXCLUDED.url", "last_seen_at=NOW()", "updated_at=NOW()", "parsed_at=EXCLUDED.parsed_at"]
    for column in LISTING_COLUMNS:
        if column in {"source", "external_id", "operation", "url", "raw_listing_id", "parsed_at"}:
            continue
        if column in TEXT_COLUMNS:
            updates.append(f"{column}=COALESCE(NULLIF(EXCLUDED.{column}, ''), commercial_listings.{column})")
        elif column in {"phones", "photos", "validation_errors"}:
            updates.append(f"{column}=CASE WHEN cardinality(EXCLUDED.{column}) > 0 THEN EXCLUDED.{column} ELSE commercial_listings.{column} END")
        elif column == "extraction_confidence":
            updates.append(f"{column}=EXCLUDED.{column}")
        else:
            updates.append(f"{column}=COALESCE(EXCLUDED.{column}, commercial_listings.{column})")
    updates.append("status=CASE WHEN commercial_listings.status IN ('quarantine','archived') THEN commercial_listings.status ELSE 'active' END")
    sql = f"""
        INSERT INTO commercial_listings ({columns}) VALUES ({placeholders})
        ON CONFLICT (source, external_id) DO UPDATE SET {', '.join(updates)}
        RETURNING id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, values)
        return cursor.fetchone()[0]


def existing_external_ids(connection, source: str, operation: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT external_id FROM commercial_listings WHERE source=%s AND operation=%s",
            (source, operation),
        )
        return {row[0] for row in cursor.fetchall()}
