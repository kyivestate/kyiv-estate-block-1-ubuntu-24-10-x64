BEGIN;

CREATE TABLE IF NOT EXISTS commercial_raw_listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('olx', 'rieltor')),
    operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER NOT NULL DEFAULT 0,
    raw_html TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS commercial_raw_status_idx
    ON commercial_raw_listings (source, operation, parse_status, fetched_at DESC);

CREATE TABLE IF NOT EXISTS commercial_listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('olx', 'rieltor')),
    external_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'quarantine', 'archived')),
    url TEXT NOT NULL,
    commercial_type TEXT NOT NULL DEFAULT 'multifunctional',
    commercial_subtype TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    ai_title TEXT NOT NULL DEFAULT '',
    ai_description TEXT NOT NULL DEFAULT '',
    price_amount NUMERIC(18,2),
    price_currency TEXT NOT NULL DEFAULT 'UNKNOWN',
    price_period TEXT NOT NULL DEFAULT 'unknown',
    price_uah NUMERIC(18,2),
    price_usd NUMERIC(18,2),
    price_eur NUMERIC(18,2),
    price_per_m2 NUMERIC(18,4),
    price_per_m2_currency TEXT NOT NULL DEFAULT 'UNKNOWN',
    price_per_m2_uah NUMERIC(18,4),
    price_per_m2_usd NUMERIC(18,4),
    price_per_m2_eur NUMERIC(18,4),
    price_per_m2_period TEXT NOT NULL DEFAULT 'unknown',
    source_price_raw TEXT NOT NULL DEFAULT '',
    vat_included BOOLEAN,
    opex_amount NUMERIC(18,2),
    utilities_included BOOLEAN,
    deposit_months NUMERIC(8,2),
    rent_free_months NUMERIC(8,2),
    minimum_lease_months INTEGER,
    indexation_terms TEXT NOT NULL DEFAULT '',
    sale_with_tenant BOOLEAN,
    tenant_name TEXT NOT NULL DEFAULT '',
    cap_rate NUMERIC(8,4),
    area_total_m2 NUMERIC(12,2),
    area_usable_m2 NUMERIC(12,2),
    floor INTEGER,
    floors_total INTEGER,
    floor_label TEXT NOT NULL DEFAULT '',
    ceiling_height_m NUMERIC(8,2),
    layout_type TEXT NOT NULL DEFAULT '',
    condition TEXT NOT NULL DEFAULT '',
    fitout TEXT NOT NULL DEFAULT '',
    building_class TEXT NOT NULL DEFAULT '',
    year_built INTEGER,
    separate_entrance BOOLEAN,
    facade BOOLEAN,
    showcase_windows BOOLEAN,
    parking_spaces INTEGER,
    loading_dock BOOLEAN,
    ramp BOOLEAN,
    freight_elevator BOOLEAN,
    electric_power_kw NUMERIC(12,2),
    electricity_backup BOOLEAN,
    generator BOOLEAN,
    water_supply BOOLEAN,
    sewerage BOOLEAN,
    heating_type TEXT NOT NULL DEFAULT '',
    ventilation BOOLEAN,
    air_conditioning BOOLEAN,
    fire_safety BOOLEAN,
    security BOOLEAN,
    internet BOOLEAN,
    shelter_distance_m INTEGER,
    permitted_use TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT 'Київ',
    district TEXT NOT NULL DEFAULT '',
    street TEXT NOT NULL DEFAULT '',
    full_address TEXT NOT NULL DEFAULT '',
    address_confidence TEXT NOT NULL DEFAULT 'unknown',
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    advertiser_type TEXT NOT NULL DEFAULT 'unknown',
    contact_name TEXT NOT NULL DEFAULT '',
    agency_name TEXT NOT NULL DEFAULT '',
    phones TEXT[] NOT NULL DEFAULT '{}',
    commission_text TEXT NOT NULL DEFAULT '',
    contact_visibility TEXT NOT NULL DEFAULT 'unknown',
    photo_url TEXT NOT NULL DEFAULT '',
    photos TEXT[] NOT NULL DEFAULT '{}',
    extraction_confidence JSONB NOT NULL DEFAULT '{}',
    validation_errors TEXT[] NOT NULL DEFAULT '{}',
    raw_listing_id BIGINT REFERENCES commercial_raw_listings(id),
    published_at TIMESTAMPTZ,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id),
    CHECK (price_amount IS NULL OR price_amount >= 0),
    CHECK (price_per_m2 IS NULL OR price_per_m2 >= 0),
    CHECK (area_total_m2 IS NULL OR area_total_m2 > 0),
    CHECK (area_usable_m2 IS NULL OR area_usable_m2 > 0),
    CHECK (floors_total IS NULL OR floors_total > 0),
    CHECK (floor IS NULL OR floors_total IS NULL OR floor <= floors_total)
);

CREATE INDEX IF NOT EXISTS commercial_listing_active_idx
    ON commercial_listings (status, operation, commercial_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS commercial_listing_address_idx
    ON commercial_listings (city, district, street);
CREATE INDEX IF NOT EXISTS commercial_listing_identity_idx
    ON commercial_listings (source, external_id);

ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_uah NUMERIC(18,2);
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_usd NUMERIC(18,2);
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_eur NUMERIC(18,2);
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_per_m2_uah NUMERIC(18,4);
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_per_m2_currency TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS ai_title TEXT NOT NULL DEFAULT '';
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS ai_description TEXT NOT NULL DEFAULT '';
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_per_m2_usd NUMERIC(18,4);
ALTER TABLE commercial_listings ADD COLUMN IF NOT EXISTS price_per_m2_eur NUMERIC(18,4);

CREATE TABLE IF NOT EXISTS commercial_listing_status_checks (
    listing_id BIGINT PRIMARY KEY REFERENCES commercial_listings(id) ON DELETE CASCADE,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER NOT NULL DEFAULT 0,
    consecutive_missing INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS commercial_listing_enrichment_attempts (
    listing_id BIGINT PRIMARY KEY REFERENCES commercial_listings(id) ON DELETE CASCADE,
    raw_checked_at TIMESTAMPTZ,
    live_checked_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT ''
);

COMMIT;
