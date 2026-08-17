BEGIN;

CREATE TABLE IF NOT EXISTS findly_raw_listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'findly' CHECK (source = 'findly'),
    operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER NOT NULL DEFAULT 0,
    raw_json JSONB NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('parsed', 'failed')),
    error_message TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS findly_normalized_listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'findly' CHECK (source = 'findly'),
    operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    external_id TEXT NOT NULL,
    origin_source TEXT NOT NULL DEFAULT 'findly',
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    property_type TEXT NOT NULL DEFAULT '',
    price_uah NUMERIC(18,2), price_usd NUMERIC(18,2), price_eur NUMERIC(18,2),
    source_price_raw TEXT NOT NULL DEFAULT '', source_currency TEXT NOT NULL DEFAULT '',
    rooms INTEGER, area NUMERIC(10,2), floor INTEGER, floors_total INTEGER,
    district TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '', street TEXT NOT NULL DEFAULT '',
    full_address TEXT NOT NULL DEFAULT '', latitude NUMERIC(10,7), longitude NUMERIC(10,7),
    photo_url TEXT NOT NULL DEFAULT '', photos TEXT[] NOT NULL DEFAULT '{}',
    contact_name TEXT NOT NULL DEFAULT '', contact_phone TEXT NOT NULL DEFAULT '', commission TEXT NOT NULL DEFAULT '',
    extraction_confidence JSONB NOT NULL DEFAULT '{}', is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    validation_errors TEXT[] NOT NULL DEFAULT '{}', raw_listing_id BIGINT REFERENCES findly_raw_listings(id),
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS findly_listings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'findly' CHECK (source = 'findly'),
    external_id TEXT NOT NULL, operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    origin_source TEXT NOT NULL DEFAULT 'findly', url TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
    ai_title TEXT, ai_description TEXT, ai_quality_score INTEGER,
    property_type TEXT NOT NULL DEFAULT '', price_uah NUMERIC(18,2), price_usd NUMERIC(18,2), price_eur NUMERIC(18,2),
    rooms INTEGER, area NUMERIC(10,2), floor INTEGER, floors_total INTEGER,
    district TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '', street TEXT NOT NULL DEFAULT '', full_address TEXT NOT NULL DEFAULT '',
    latitude NUMERIC(10,7), longitude NUMERIC(10,7), photo_url TEXT NOT NULL DEFAULT '', photos TEXT[] NOT NULL DEFAULT '{}',
    contact_name TEXT NOT NULL DEFAULT '', contact_phone TEXT NOT NULL DEFAULT '', commission TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'quarantine', 'archived')),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), parsed_at TIMESTAMPTZ,
    comments TEXT NOT NULL DEFAULT '', data_completeness INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS findly_listings_status_operation_updated_idx ON findly_listings(status, operation, updated_at);
CREATE INDEX IF NOT EXISTS findly_raw_listings_parse_status_idx ON findly_raw_listings(parse_status, fetched_at);

CREATE TABLE IF NOT EXISTS findly_collection_runs (
    id BIGSERIAL PRIMARY KEY, operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), completed_at TIMESTAMPTZ,
    expected_pages INTEGER NOT NULL DEFAULT 0, successful_pages INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')), error_message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS findly_listing_status_checks (
    listing_id BIGINT PRIMARY KEY REFERENCES findly_listings(id), checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    missing_complete_runs INTEGER NOT NULL DEFAULT 0, last_seen_at TIMESTAMPTZ, note TEXT NOT NULL DEFAULT ''
);
COMMIT;
