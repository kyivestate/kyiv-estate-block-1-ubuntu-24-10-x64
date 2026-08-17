from __future__ import annotations
import asyncio
import os
import re
from olx_phone_coverage.services.db import get_pool
from olx_phone_coverage.google.sheet_reader import read_olx_rows

def normalize_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"#.*$", "", url)
    url = re.sub(r"\?.*$", "", url)
    return url.rstrip("/")

def extract_external_id(url: str) -> str | None:
    m = re.search(r'(ID[0-9A-Za-z]+)\.html', url)
    if m:
        return "olx_" + m.group(1)
    return None

async def main():
    spreadsheet_id = os.environ["SOURCE_SPREADSHEET_ID"]
    worksheet_name = os.environ["SOURCE_WORKSHEET_NAME"]

    rows = read_olx_rows(spreadsheet_id, worksheet_name)
    pool = await get_pool()

    async with pool.acquire() as conn:
        for item in rows:
            normalized_url = normalize_url(item["url"])
            external_id = extract_external_id(normalized_url)
            await conn.execute(
                """
                INSERT INTO olx_sheet_phone_jobs
                (source_sheet_name, source_row_number, source_url, normalized_url, external_id, next_attempt_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (source_sheet_name, source_row_number)
                DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    normalized_url = EXCLUDED.normalized_url,
                    external_id = EXCLUDED.external_id,
                    updated_at = NOW()
                """,
                item["sheet_name"],
                item["row_number"],
                item["url"],
                normalized_url,
                external_id,
            )

    await pool.close()
    print(f"Imported {len(rows)} OLX rows from sheet")

if __name__ == "__main__":
    asyncio.run(main())
