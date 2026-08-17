#!/usr/bin/env python3
"""Register permanent Kyiv Estate listing-card URLs without touching Sheets."""
from __future__ import annotations

import json
import os

import psycopg2

PUBLIC_BASE = os.getenv("MEDIA_PUBLIC_BASE", "https://macbook-pro-4.taila50e89.ts.net").rstrip("/")
TABLES = {
    "apartments": "active_listings",
    "houses": "houses_listings",
    "commercial": "commercial_listings",
}


def main() -> None:
    with psycopg2.connect(host=os.getenv("PG_HOST", "/tmp"), port=os.getenv("PG_PORT", "5432"), dbname=os.getenv("PG_DBNAME", "real_estate"), user=os.getenv("PG_USER", "admin"), password=os.getenv("PG_PASSWORD", "")) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS block3.listing_pages (
                    catalog text NOT NULL,
                    listing_id bigint NOT NULL,
                    url text NOT NULL,
                    source_updated_at timestamptz,
                    active boolean NOT NULL DEFAULT true,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY(catalog, listing_id)
                )
            """)
            totals = {}
            for catalog, table in TABLES.items():
                cur.execute(f"""
                    INSERT INTO block3.listing_pages(catalog,listing_id,url,source_updated_at,active)
                    SELECT %s,id,%s || '/listing/' || %s || '/' || id::text,updated_at,true
                    FROM {table}
                    WHERE status='active'
                    ON CONFLICT(catalog,listing_id) DO UPDATE SET
                        url=EXCLUDED.url, source_updated_at=EXCLUDED.source_updated_at,
                        active=true, updated_at=now()
                """, (catalog, PUBLIC_BASE, catalog))
                totals[catalog] = cur.rowcount
                cur.execute(f"""
                    UPDATE block3.listing_pages page SET active=false,updated_at=now()
                    WHERE catalog=%s AND active=true
                      AND NOT EXISTS (SELECT 1 FROM {table} source WHERE source.id=page.listing_id AND source.status='active')
                """, (catalog,))
            cur.execute("SELECT count(*) FROM block3.listing_pages WHERE active=true")
            total = cur.fetchone()[0]
    print(json.dumps({"registered": totals, "active_pages": total, "base": PUBLIC_BASE}, ensure_ascii=False))


if __name__ == "__main__":
    main()
