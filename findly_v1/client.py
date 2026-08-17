"""Rate-limited Findly API client. It never logs cookie values."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from findly_v1.config import cfg


class FindlyClient:
    def __init__(self, cookie_file: Path | None = None):
        self.cookie_file = cookie_file or cfg.cookie_file
        if not self.cookie_file or not self.cookie_file.is_file():
            raise RuntimeError('FINDLY_COOKIE_FILE is not configured or does not exist')
        cookie = self.cookie_file.read_text(encoding='utf-8').strip()
        if not cookie:
            raise RuntimeError('FINDLY_COOKIE_FILE is empty')
        self.headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Cookie': cookie, 'Referer': 'https://findly.com.ua/'}

    async def _request(self, client: httpx.AsyncClient, method: str, path: str) -> tuple[int, dict[str, Any] | None]:
        url = f'{cfg.base_url.rstrip("/")}{path}'
        for attempt in range(cfg.retries):
            try:
                response = await client.request(method, url, headers=self.headers)
                if response.status_code == 200:
                    payload = response.json()
                    return response.status_code, payload if isinstance(payload, dict) else None
                if response.status_code in (429, 503) and attempt + 1 < cfg.retries:
                    await asyncio.sleep(min(30, 2 ** (attempt + 1)))
                    continue
                return response.status_code, None
            except (httpx.HTTPError, json.JSONDecodeError):
                if attempt + 1 < cfg.retries:
                    await asyncio.sleep(2 ** attempt)
        return 0, None

    async def auth(self, client: httpx.AsyncClient) -> tuple[int, dict[str, Any] | None]:
        return await self._request(client, 'GET', '/api/me')

    async def page(self, client: httpx.AsyncClient, operation: str, page: int) -> tuple[int, dict[str, Any] | None]:
        return await self._request(client, 'GET', f'/api/properties?page={page}&limit={cfg.per_page}&type={operation}&city_id=1')

    async def phone(self, client: httpx.AsyncClient, external_id: str) -> tuple[int, dict[str, Any] | None]:
        """Potentially credit-consuming endpoint; call only via an explicit CLI flag."""
        return await self._request(client, 'POST', f'/api/properties/{external_id}/contact')
