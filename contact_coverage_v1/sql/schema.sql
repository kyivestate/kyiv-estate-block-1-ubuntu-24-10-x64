BEGIN;

CREATE TABLE IF NOT EXISTS contact_coverage_listings (
    id BIGSERIAL PRIMARY KEY,
    catalog TEXT NOT NULL CHECK (catalog IN ('apartments', 'houses', 'commercial')),
    listing_id BIGINT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('olx', 'rieltor')),
    external_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('rent', 'buy')),
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'quarantine', 'archived')),
    source_url TEXT NOT NULL,
    contact_method TEXT NOT NULL CHECK (contact_method IN ('public_phone', 'source_link', 'unavailable')),
    contact_phone TEXT NOT NULL DEFAULT '',
    phone_count INTEGER NOT NULL DEFAULT 0 CHECK (phone_count >= 0),
    phone_origin TEXT NOT NULL DEFAULT '' CHECK (phone_origin IN ('', 'public_listing_field', 'public_text_candidate')),
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (catalog, source, external_id)
);

CREATE INDEX IF NOT EXISTS contact_coverage_active_source_idx
    ON contact_coverage_listings (status, source, contact_method, updated_at DESC);

COMMIT;
