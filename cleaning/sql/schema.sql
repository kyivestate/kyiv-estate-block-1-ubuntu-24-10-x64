CREATE TABLE IF NOT EXISTS cleaning_listing_checks (
    catalog TEXT NOT NULL CHECK (catalog IN ('apartments','houses','commercial')),
    listing_id BIGINT NOT NULL, checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status INTEGER, consecutive_missing INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (catalog, listing_id)
);
CREATE TABLE IF NOT EXISTS cleaning_archives (
    catalog TEXT NOT NULL, listing_id BIGINT NOT NULL, archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason TEXT NOT NULL, snapshot JSONB NOT NULL, PRIMARY KEY (catalog, listing_id)
);
