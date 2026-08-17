BEGIN;

CREATE TABLE IF NOT EXISTS olx_sheet_urls (
    id BIGSERIAL PRIMARY KEY,
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    external_id TEXT,
    UNIQUE (sheet_name, row_number),
    UNIQUE (normalized_url)
);

CREATE TABLE IF NOT EXISTS olx_phone_jobs (
    id BIGSERIAL PRIMARY KEY,
    url_id BIGINT NOT NULL REFERENCES olx_sheet_urls(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_http_status INTEGER,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_olx_phone_jobs_status_next ON olx_phone_jobs(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS olx_phones (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES olx_phone_jobs(id) ON DELETE CASCADE,
    url_id BIGINT NOT NULL REFERENCES olx_sheet_urls(id) ON DELETE CASCADE,
    external_id TEXT,
    ad_id TEXT,
    phone_e164 TEXT NOT NULL,
    phone_raw TEXT,
    all_phones_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    strategy TEXT NOT NULL,
    http_status INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id)
);

CREATE INDEX IF NOT EXISTS idx_olx_phones_e164 ON olx_phones(phone_e164);
CREATE INDEX IF NOT EXISTS idx_olx_phones_ad_id ON olx_phones(ad_id);

CREATE TABLE IF NOT EXISTS olx_phone_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES olx_phone_jobs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    endpoint TEXT,
    http_status INTEGER,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    error_text TEXT,
    response_preview TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_olx_phone_attempts_job ON olx_phone_attempts(job_id);

COMMIT;
