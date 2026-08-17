BEGIN;

CREATE TABLE IF NOT EXISTS houses_raw_listings (
    id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, operation TEXT NOT NULL CHECK (operation IN ('rent','buy')),
    external_id TEXT NOT NULL, url TEXT NOT NULL, fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER NOT NULL DEFAULT 0, raw_html TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '', parse_status TEXT NOT NULL DEFAULT 'pending', error_message TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS houses_normalized_listings (
    id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, operation TEXT NOT NULL CHECK (operation IN ('rent','buy')),
    external_id TEXT NOT NULL, url TEXT NOT NULL, property_type TEXT NOT NULL DEFAULT 'Будинок' CHECK (property_type = 'Будинок'),
    title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_uah NUMERIC(18,2), price_usd NUMERIC(18,2), price_eur NUMERIC(18,2),
    source_price_raw TEXT NOT NULL DEFAULT '', source_currency TEXT NOT NULL DEFAULT '', rooms INTEGER, area NUMERIC(10,2),
    floor INTEGER, floor_total INTEGER, agent_type TEXT NOT NULL DEFAULT 'unknown', contact_name TEXT NOT NULL DEFAULT '', contact_phone TEXT NOT NULL DEFAULT '',
    commission TEXT NOT NULL DEFAULT '', residential_complex TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT 'Київ', district TEXT NOT NULL DEFAULT '',
    street TEXT NOT NULL DEFAULT '', metro_station TEXT NOT NULL DEFAULT '', full_address TEXT NOT NULL DEFAULT '', photo_url TEXT NOT NULL DEFAULT '',
    photos TEXT[] NOT NULL DEFAULT '{}', extraction_confidence JSONB NOT NULL DEFAULT '{}', is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    validation_errors TEXT[] NOT NULL DEFAULT '{}', raw_listing_id BIGINT REFERENCES houses_raw_listings(id), parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS houses_listings (
    id BIGSERIAL PRIMARY KEY, external_id TEXT NOT NULL, source TEXT NOT NULL, operation TEXT NOT NULL CHECK (operation IN ('rent','buy')),
    property_type TEXT NOT NULL DEFAULT 'Будинок' CHECK (property_type = 'Будинок'), title TEXT, description TEXT, ai_description TEXT,
    price_uah NUMERIC(18,2), price_usd NUMERIC(18,2), price_eur NUMERIC(18,2), area NUMERIC(10,2), floor INTEGER, floors_total INTEGER,
    rooms INTEGER, district TEXT, city TEXT DEFAULT 'Київ', street TEXT, residential_complex TEXT, metro_station TEXT, url TEXT, photo_url TEXT,
    photos TEXT[] DEFAULT '{}', commission TEXT, agent_type TEXT, agent_name TEXT, agent_phone TEXT, status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','inactive','quarantine','archived')), comments TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), parsed_at TIMESTAMPTZ, ai_title TEXT, ai_quality_score INTEGER, data_completeness INTEGER,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS houses_listings_status_operation_updated_idx ON houses_listings(status, operation, updated_at);
CREATE INDEX IF NOT EXISTS houses_raw_listings_parse_status_idx ON houses_raw_listings(source, parse_status);

CREATE TABLE IF NOT EXISTS houses_listing_status_checks (
    listing_id BIGINT PRIMARY KEY REFERENCES houses_listings(id), checked_at TIMESTAMPTZ NOT NULL,
    http_status INTEGER, error_text TEXT, missing_count INTEGER NOT NULL DEFAULT 0, last_seen_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS houses_listing_enrichment_attempts (
    listing_id BIGINT PRIMARY KEY REFERENCES houses_listings(id), raw_checked_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS houses_listing_live_enrichment_attempts (
    listing_id BIGINT PRIMARY KEY REFERENCES houses_listings(id), checked_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS houses_ai_content_rebuilds (
    listing_id BIGINT PRIMARY KEY REFERENCES houses_listings(id), version INTEGER NOT NULL, rebuilt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMIT;
