from __future__ import annotations
import os
import asyncpg

async def get_pool():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        dsn = "postgresql://localhost:5432/real_estate"
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
