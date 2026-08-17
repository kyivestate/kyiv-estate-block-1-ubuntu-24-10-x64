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
import asyncpg

OLX = "https://www.olx.ua"

def norm_phone(raw: str | None) -> str | None:
    if not raw: return None
    raw = raw.strip()
    try:
        n = phonenumbers.parse(raw, "UA")
        if phonenumbers.is_valid_number(n):
            return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    digits = re.sub(r"\D+", "", raw)
    return digits or None

def extract_ad_id(html: str) -> str | None:
    for pat in [r'"ad_id"\s*:\s*"?(\d+)"?', r'"id"\s*:\s*(\d+)', r'data-ad-id="(\d+)"', r'"list_id"\s*:\s*"?(\d+)"?']:
        m = re.search(pat, html)
        if m: return m.group(1)
    return None

class Worker:
    def __init__(self):
        self.s = Session(impersonate="chrome")
        self.s.headers.update({
            "accept-language": "uk-UA,uk;q=0.9,en;q=0.8",
            "x-platform-type": "mobile-html5",
            "user-agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        })
    def get(self, url: str):
        time.sleep(random.uniform(1.2, 2.8))
        return self.s.get(url, timeout=30)

async def claim_jobs(conn, limit: int):
    rows = await conn.fetch("""
        UPDATE olx_phone_jobs j
        SET status='processing', updated_at=NOW()
        FROM (
            SELECT id FROM olx_phone_jobs
            WHERE status IN ('pending','retry') AND COALESCE(next_attempt_at, NOW()) <= NOW()
            ORDER BY id LIMIT $1 FOR UPDATE SKIP LOCKED
        ) sub
        WHERE j.id = sub.id
        RETURNING j.id, j.url_id, j.attempt_count
    """, limit)
    return rows

async def get_url(conn, url_id):
    return await conn.fetchrow("SELECT id, normalized_url, external_id FROM olx_sheet_urls WHERE id=$1", url_id)

async def log_attempt(conn, job_id, attempt_no, strategy, endpoint, http_status, success, error, preview):
    await conn.execute("""
        INSERT INTO olx_phone_attempts (job_id, attempt_no, strategy, endpoint, http_status, success, error_text, response_preview)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
    """, job_id, attempt_no, strategy, endpoint, http_status, success, error, preview)

async def save_phones(conn, job, url_row, ad_id, phones, strategy, http_listing, http_phone, coverage):
    norm = [norm_phone(p) for p in phones if p]
    norm = [p for p in norm if p]
    if not norm: return
    await conn.execute("""
        INSERT INTO olx_phones (job_id, url_id, external_id, ad_id, phone_e164, phone_raw, all_phones_json, strategy, http_status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (job_id) DO UPDATE SET
            phone_e164=EXCLUDED.phone_e164, phone_raw=EXCLUDED.phone_raw,
            all_phones_json=EXCLUDED.all_phones_json, strategy=EXCLUDED.strategy, http_status=EXCLUDED.http_status
    """, job["id"], url_row["id"], url_row["external_id"], ad_id, norm[0], phones[0], json.dumps(norm), strategy, http_phone)

async def finalize(conn, job_id, status, attempt_count, http_status, error, retry_min=None):
    if retry_min:
        await conn.execute("""
            UPDATE olx_phone_jobs SET status=$2, attempt_count=$3, last_http_status=$4, last_error=$5,
                next_attempt_at=NOW() + ($6 || ' min')::interval, updated_at=NOW() WHERE id=$1
        """, job_id, status, attempt_count, http_status, error, retry_min)
    else:
        await conn.execute("""
            UPDATE olx_phone_jobs SET status=$2, attempt_count=$3, last_http_status=$4, last_error=$5, updated_at=NOW() WHERE id=$1
        """, job_id, status, attempt_count, http_status, error)

async def process_one(conn, worker, job):
    attempt = job["attempt_count"] + 1
    url_row = await get_url(conn, job["url_id"])
    if not url_row: return

    r = worker.get(url_row["normalized_url"])
    await log_attempt(conn, job["id"], attempt, "listing_html", url_row["normalized_url"], r.status_code, r.status_code==200, None, r.text[:500] if r.text else None)

    if r.status_code != 200:
        retry = attempt < 6 and r.status_code in (403,429,500,502,503,504)
        await finalize(conn, job["id"], "retry" if retry else "failed", attempt, r.status_code, f"listing {r.status_code}", 30 if retry else None)
        return

    ad_id = extract_ad_id(r.text)
    if not ad_id:
        await finalize(conn, job["id"], "failed", attempt, r.status_code, "ad_id not found")
        return

    phone_status = None
    phones = []
    for ep in [f"{OLX}/api/v1/offers/{ad_id}/phones/", f"{OLX}/api/v1/offers/{ad_id}/limited-phones/"]:
        pr = worker.get(ep)
        phone_status = pr.status_code
        if pr.status_code == 200:
            try:
                data = pr.json()
                phones = data.get("data", {}).get("phones", []) or []
                if phones: break
            except: pass
        if pr.status_code in (401,403,429):
            break
    await log_attempt(conn, job["id"], attempt, "phone_api", ep, phone_status, bool(phones), None, json.dumps(phones)[:500] if phones else None)

    if phones:
        await save_phones(conn, job, url_row, ad_id, phones, "phone_api", r.status_code, phone_status, "found")
        await finalize(conn, job["id"], "done", attempt, phone_status, None)
        return

    retry = attempt < 6 and phone_status in (401,403,429,500,502,503,504,None)
    await finalize(conn, job["id"], "retry" if retry else "failed", attempt, phone_status, f"phone api {phone_status}", 45 if retry else None)

async def main():
    batch = int(os.getenv("OLX_PHONE_BATCH", "20"))
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL", "postgresql://localhost:5432/real_estate"), min_size=1, max_size=5)
    worker = Worker()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO olx_phone_jobs (url_id)
            SELECT u.id FROM olx_sheet_urls u
            LEFT JOIN olx_phone_jobs j ON j.url_id = u.id
            WHERE j.id IS NULL
        """)
        jobs = await claim_jobs(conn, batch)

    if not jobs:
        print("No jobs")
        await pool.close(); return

    async with pool.acquire() as conn:
        for job in jobs:
            await process_one(conn, worker, job)

    await pool.close()
    print(f"Processed {len(jobs)} jobs")

if __name__ == "__main__":
    asyncio.run(main())
