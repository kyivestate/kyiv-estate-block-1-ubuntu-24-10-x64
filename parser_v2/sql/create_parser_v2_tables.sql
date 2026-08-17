BEGIN;
CREATE TABLE IF NOT EXISTS parser_v2_raw_listings (
    id SERIAL PRIMARY KEY, source TEXT NOT NULL, operation TEXT NOT NULL,
    external_id TEXT NOT NULL, url TEXT, fetched_at TIMESTAMPTZ DEFAULT NOW(),
    http_status INTEGER DEFAULT 0, raw_html TEXT DEFAULT '', raw_json TEXT DEFAULT '',
    content_hash TEXT DEFAULT '', parse_status TEXT DEFAULT 'pending',
    error_message TEXT DEFAULT '', retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_v2_raw_src ON parser_v2_raw_listings(source, parse_status);

CREATE TABLE IF NOT EXISTS parser_v2_normalized_listings (
    id SERIAL PRIMARY KEY, source TEXT NOT NULL, operation TEXT NOT NULL, property_type TEXT DEFAULT 'Квартира',
    external_id TEXT NOT NULL, url TEXT, title TEXT DEFAULT '', description TEXT DEFAULT '',
    price_uah NUMERIC(18,2), price_usd NUMERIC(18,2), price_eur NUMERIC(18,2),
    source_price_raw TEXT DEFAULT '', source_currency TEXT DEFAULT '',
    rooms INTEGER, area NUMERIC(10,2), floor INTEGER, floor_total INTEGER,
    agent_type TEXT DEFAULT 'unknown', contact_name TEXT DEFAULT '', contact_phone TEXT DEFAULT '',
    commission TEXT DEFAULT '', residential_complex TEXT DEFAULT '',
    city TEXT DEFAULT 'Київ', district TEXT DEFAULT '', street TEXT DEFAULT '', metro_station TEXT DEFAULT '', full_address TEXT DEFAULT '',
    photo_url TEXT DEFAULT '', photos TEXT[] DEFAULT '{}',
    cdn_photo_url TEXT DEFAULT '', cdn_photos TEXT[] DEFAULT '{}',
    sheet_image_formula TEXT DEFAULT '', extraction_confidence JSONB DEFAULT '{}',
    is_valid BOOLEAN DEFAULT true, validation_errors TEXT[] DEFAULT '{}',
    raw_listing_id INTEGER REFERENCES parser_v2_raw_listings(id),
    merged_to_active_at TIMESTAMPTZ, parsed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_v2_norm_valid ON parser_v2_normalized_listings(is_valid);
ALTER TABLE parser_v2_normalized_listings ADD COLUMN IF NOT EXISTS property_type TEXT DEFAULT 'Квартира';
ALTER TABLE parser_v2_normalized_listings ADD COLUMN IF NOT EXISTS metro_station TEXT DEFAULT '';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='active_listings_source_external_id_key') THEN
        ALTER TABLE active_listings ADD CONSTRAINT active_listings_source_external_id_key UNIQUE (source, external_id);
    END IF;
EXCEPTION WHEN others THEN RAISE NOTICE 'Constraint may already exist'; END $$;
COMMIT;
