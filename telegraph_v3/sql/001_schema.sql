CREATE SCHEMA IF NOT EXISTS block3;

CREATE TABLE IF NOT EXISTS block3.publications (
    catalog text NOT NULL CHECK (catalog IN ('apartments', 'houses', 'commercial')),
    listing_id bigint NOT NULL,
    source text NOT NULL,
    external_id text NOT NULL,
    operation text NOT NULL CHECK (operation IN ('rent', 'buy')),
    ua_url text,
    en_url text,
    source_updated_at timestamptz,
    content_fingerprint text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'publishing', 'published', 'retry', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    published_at timestamptz,
    synced_at timestamptz,
    sync_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog, listing_id),
    UNIQUE (catalog, source, external_id, operation)
);

ALTER TABLE block3.publications
    ADD COLUMN IF NOT EXISTS retry_after timestamptz;

CREATE TABLE IF NOT EXISTS block3.media_assets (
    sha256 text PRIMARY KEY,
    source_url text NOT NULL UNIQUE,
    cloudinary_public_id text NOT NULL,
    secure_url text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS block3.translations (
    source_sha256 text PRIMARY KEY,
    source_text text NOT NULL,
    english_text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS block3_publications_work_idx
    ON block3.publications (status, updated_at, catalog, listing_id);
