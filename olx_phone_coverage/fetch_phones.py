from __future__ import annotations
import asyncio
import json
import os
import random
import re
import time
import phonenumbers
from bs4 import BeautifulSoup
from curl_cffi.requests import Session

from olx_phone_coverage.services.db import get_pool

OLX_BASE = "https://www.olx.ua"

def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        num = phonenumbers.parse(raw, "UA")
        if phonenumbers.is_possible_number(num) and phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    digits = re.sub(r"\D+", "", raw)
    return digits or None

def extract_external_id_from_url(url: str) -> str | None:
    m = re.search(r'(ID[0-9A-Za-z]+)\.html', url)
    if m:
        return "olx_" + m.group(1)
    return None

def extract_ad_id(html: str) -> str | None:
    patterns = [
        r'"ad_id"\s*:\s*"?(\\d+)"?',
        r'"id"\s*:\s*(\\d+)',
        r'data-ad-id="(\\d+)"',
        r'"list_id"\s*:\s*"?(\\d+)"?'
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return None

class OlxPhoneWorker:
    def __init__(self):
        self.session = Session(impersonate="chrome")
        self.session.headers.update({
            "accept-language": "uk-UA,uk;q=0.9,en;q=0.8",
            "x-platform-type": "mobile-html5",
            "user-agent": (
                "Mozilla/5.0 (Linux; Android 14; SM-S918B) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Mobile Safari/537.36"
            ),
        })

    def get(self, url: str):
        time.sleep(random.uniform(1.2, 2.8))
        return self.session.get(url, timeout=30)

    def fetch_listing(self, url: str):
        return self.get(url)

    def fetch_phone_api(self, ad_id: str):
        endpoints = [
            f"{OLX_BASE}/api/v1/offers/{ad_id}/phones/",
            f"{OLX_BASE}/api/v1/offers/{ad_id}/limited-phones/",
        ]
        for ep in endpoints:
            resp = self.get(ep)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    phones = data.get("data", {}).get("phones", []) or []
                    if phones:
                        return resp.status_code, phones, ep
                except Exception:
                    pass
            if resp.status_code in (401, 403, 429):
                return resp.status_code, [], ep
        return None, [], None

async def claim_jobs(conn, limit: int):
    rows = await conn.fetch(
        """
        UPDATE olx_sheet_phone_jobs
        SET status = 'processing',
            updated_at = NOW()
        WHERE id IN (
            SELECT id
            FROM olx_sheet_phone_jobs
            WHERE status IN ('pending', 'retry')
              AND COALESCE(next_attempt_at, NOW()) <= NOW()
            ORDER BY id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, source_sheet_name, source_row_number, source_url, normalized_url, external_id, attempt_count
        """,
        limit
    )
    return rows

async def save_attempt(conn, job_id, attempt_no, strategy, request_url, http_status, success, error_text, response_excerpt):
    await conn.execute(
        """
        INSERT INTO olx_sheet_phone_attempts
        (job_id, attempt_no, strategy, request_url, http_status, success, error_text, response_excerpt)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        job_id, attempt_no, strategy, request_url, http_status, success, error_text, response_excerpt
    )

async def mark_result(conn, job, listing_status, phone_status, ad_id, phones, strategy, coverage_status, note=None):
    normalized = [normalize_phone(p) for p in phones if p]
    normalized = [p for p in normalized if p]
    phone_raw = phones[0] if phones else None
    phone_normalized = normalized[0] if normalized else None
    contact_method = "public_phone" if phones else "source_link"

    await conn.execute(
        """
        INSERT INTO olx_sheet_phone_results
        (
            job_id, source_sheet_name, source_row_number, source_url, normalized_url,
            external_id, ad_id, contact_method, phone_raw, phone_normalized,
            phones_json, phone_count, phone_origin, parser_strategy,
            http_status_listing, http_status_phone_api, coverage_status,
            note, fetched_at, updated_at
        )
        VALUES
        ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14,$15,$16,$17,$18,NOW(),NOW())
        ON CONFLICT (job_id)
        DO UPDATE SET
            external_id = EXCLUDED.external_id,
            ad_id = EXCLUDED.ad_id,
            contact_method = EXCLUDED.contact_method,
            phone_raw = EXCLUDED.phone_raw,
            phone_normalized = EXCLUDED.phone_normalized,
            phones_json = EXCLUDED.phones_json,
            phone_count = EXCLUDED.phone_count,
            phone_origin = EXCLUDED.phone_origin,
            parser_strategy = EXCLUDED.parser_strategy,
            http_status_listing = EXCLUDED.http_status_listing,
            http_status_phone_api = EXCLUDED.http_status_phone_api,
            coverage_status = EXCLUDED.coverage_status,
            note = EXCLUDED.note,
            fetched_at = EXCLUDED.fetched_at,
            updated_at = NOW()
        """,
        job["id"], job["source_sheet_name"], job["source_row_number"], job["source_url"], job["normalized_url"],
        job["external_id"], ad_id, contact_method, phone_raw, phone_normalized,
        json.dumps(normalized), len(normalized), "olx_phone_api", strategy,
        listing_status, phone_status, coverage_status, note
    )

async def finalize_job(conn, job_id, status, attempt_count, last_http_status=None, last_error=None, retry_after_minutes=None):
    if retry_after_minutes:
        await conn.execute(
            """
            UPDATE olx_sheet_phone_jobs
            SET status = $2,
                attempt_count = $3,
                last_http_status = $4,
                last_error = $5,
                last_attempt_at = NOW(),
                next_attempt_at = NOW() + ($6 || ' minutes')::interval,
                updated_at = NOW()
            WHERE id = $1
            """,
            job_id, status, attempt_count, last_http_status, last_error, retry_after_minutes
        )
    else:
        await conn.execute(
            """
            UPDATE olx_sheet_phone_jobs
            SET status = $2,
                attempt_count = $3,
                last_http_status = $4,
                last_error = $5,
                last_attempt_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            """,
            job_id, status, attempt_count, last_http_status, last_error
        )

async def process_one(conn, worker, job):
    attempt_no = job["attempt_count"] + 1
    listing_status = None
    phone_status = None
    ad_id = None
    try:
        resp = worker.fetch_listing(job["normalized_url"])
        listing_status = resp.status_code
        excerpt = resp.text[:500] if resp.text else None
        await save_attempt(conn, job["id"], attempt_no, "listing_html", job["normalized_url"], listing_status, listing_status == 200, None, excerpt)

        if listing_status != 200:
            retry = attempt_no < 6 and listing_status in (403, 429, 500, 502, 503, 504)
            await mark_result(conn, job, listing_status, None, None, [], "listing_html", "blocked" if retry else "not_found", f"listing status {listing_status}")
            await finalize_job(conn, job["id"], "retry" if retry else "failed", attempt_no, listing_status, f"listing status {listing_status}", 30 if retry else None)
            return

        ad_id = extract_ad_id(resp.text)
        if not ad_id:
            ext = extract_external_id_from_url(job["normalized_url"])
            await mark_result(conn, job, listing_status, None, None, [], "listing_html", "needs_review", "ad_id not extracted")
            await finalize_job(conn, job["id"], "failed", attempt_no, listing_status, f"ad_id not extracted ext={ext}")
            return

        phone_status, phones, endpoint = worker.fetch_phone_api(ad_id)
        await save_attempt(conn, job["id"], attempt_no, "phone_api", endpoint, phone_status, bool(phones), None, json.dumps(phones)[:500] if phones else None)

        if phones:
            await mark_result(conn, job, listing_status, phone_status, ad_id, phones, "phone_api", "found")
            await finalize_job(conn, job["id"], "done", attempt_no, phone_status, None)
            return

        retry = attempt_no < 6 and phone_status in (401, 403, 429, 500, 502, 503, 504, None)
        coverage_status = "blocked" if retry else "not_found"
        await mark_result(conn, job, listing_status, phone_status, ad_id, [], "phone_api", coverage_status, f"phone api status {phone_status}")
        await finalize_job(conn, job["id"], "retry" if retry else "failed", attempt_no, phone_status, f"phone api status {phone_status}", 45 if retry else None)

    except Exception as e:
        await save_attempt(conn, job["id"], attempt_no, "exception", job["normalized_url"], None, False, str(e), None)
        retry = attempt_no < 6
        await mark_result(conn, job, listing_status, phone_status, ad_id, [], "exception", "blocked" if retry else "failed", str(e)[:500])
        await finalize_job(conn, job["id"], "retry" if retry else "failed", attempt_no, phone_status, str(e)[:500], 60 if retry else None)

async def main():
    batch_size = int(os.getenv("OLX_PHONE_BATCH_SIZE", "20"))
    pool = await get_pool()
    worker = OlxPhoneWorker()

    async with pool.acquire() as conn:
        jobs = await claim_jobs(conn, batch_size)

    if not jobs:
        print("No jobs available")
        await pool.close()
        return

    async with pool.acquire() as conn:
        for job in jobs:
            await process_one(conn, worker, job)

    await pool.close()
    print(f"Processed {len(jobs)} jobs")

if __name__ == "__main__":
    asyncio.run(main())
