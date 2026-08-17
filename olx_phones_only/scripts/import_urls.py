from __future__ import annotations
import asyncio
import os
import re
import gspread
from google.oauth2.service_account import Credentials
import asyncpg

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def get_gc():
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)

def find_url_col(headers):
    cand = ["url", "source_url", "listing_url", "ad_url", "link", "посилання", "url olx", "olx url"]
    hmap = {h.strip().lower(): i for i, h in enumerate(headers) if h}
    for c in cand:
        if c in hmap:
            return hmap[c]
    raise RuntimeError("URL column not found")

def is_olx(u: str) -> bool:
    return u and ("olx.ua/" in u.lower() or "olx.com/" in u.lower())

def norm_url(u: str) -> str:
    u = u.strip()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"\?.*$", "", u)
    return u.rstrip("/")

def ext_id(u: str) -> str | None:
    m = re.search(r'(ID[0-9A-Za-z]+)\.html', u)
    return "olx_" + m.group(1) if m else None

async def main():
    spreadsheet_id = os.environ["SOURCE_SPREADSHEET_ID"]
    worksheet_name = os.environ["SOURCE_WORKSHEET_NAME"]

    gc = get_gc()
    ws = gc.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    vals = ws.get_all_values()
    if not vals:
        print("Empty sheet"); return

    url_idx = find_url_col(vals[0])
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL", "postgresql://localhost:5432/real_estate"), min_size=1, max_size=3)

    async with pool.acquire() as conn:
        cnt = 0
        for i, row in enumerate(vals[1:], start=2):
            url = row[url_idx].strip() if url_idx < len(row) else ""
            if not is_olx(url): continue
            nu = norm_url(url)
            eid = ext_id(nu)
            await conn.execute("""
                INSERT INTO olx_sheet_urls (sheet_name, row_number, url, normalized_url, external_id)
                VALUES ($1,$2,$3,$4,$5)
                ON CONFLICT (sheet_name, row_number) DO UPDATE SET
                    url=EXCLUDED.url, normalized_url=EXCLUDED.normalized_url, external_id=EXCLUDED.external_id
            """, worksheet_name, i, url, nu, eid)
            cnt += 1
        print(f"Imported {cnt} OLX URLs")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
