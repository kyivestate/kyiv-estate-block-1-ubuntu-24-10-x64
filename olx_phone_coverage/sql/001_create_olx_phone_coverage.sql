BEGIN;

CREATE TABLE IF NOT EXISTS olx_sheet_phone_jobs (
    id BIGSERIAL PRIMARY KEY,
    source_sheet_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'olx',
    external_id TEXT,
    ad_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_http_status INTEGER,
    last_error TEXT,
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_sheet_name, source_row_number),
    UNIQUE (normalized_url)
);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_jobs_status
ON olx_sheet_phone_jobs(status);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_jobs_next_attempt
ON olx_sheet_phone_jobs(next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_jobs_external_id
ON olx_sheet_phone_jobs(external_id);

CREATE TABLE IF NOT EXISTS olx_sheet_phone_results (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES olx_sheet_phone_jobs(id) ON DELETE CASCADE,
    source_sheet_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'olx',
    external_id TEXT,
    ad_id TEXT,
    contact_method TEXT NOT NULL,
    phone_raw TEXT,
    phone_normalized TEXT,
    phones_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    phone_count INTEGER NOT NULL DEFAULT 0,
    phone_origin TEXT,
    parser_strategy TEXT,
    http_status_listing INTEGER,
    http_status_phone_api INTEGER,
    coverage_status TEXT NOT NULL DEFAULT 'not_found',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT,
    fetched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id)
);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_results_external_id
ON olx_sheet_phone_results(external_id);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_results_phone_normalized
ON olx_sheet_phone_results(phone_normalized);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_results_coverage_status
ON olx_sheet_phone_results(coverage_status);

CREATE TABLE IF NOT EXISTS olx_sheet_phone_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES olx_sheet_phone_jobs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    request_url TEXT,
    http_status INTEGER,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    error_text TEXT,
    response_excerpt TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_olx_sheet_phone_attempts_job_id
ON olx_sheet_phone_attempts(job_id);

COMMIT;
