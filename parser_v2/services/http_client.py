"""HTTP clients: curl_cffi for OLX, httpx for Rieltor."""
from __future__ import annotations
import time, random
from curl_cffi.requests import Session as CffiSession
import httpx
from parser_v2.utils.retry import retry
from parser_v2.services.logging_setup import get_logger
log = get_logger("http")

class OlxHttpClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._session = CffiSession(impersonate="chrome")
        self._last_req: float = 0; self._min_delay = 0.5

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed + random.uniform(0.1, 0.3))
        self._last_req = time.time()

    @retry(max_attempts=3, base_delay=3.0)
    def get(self, url: str) -> tuple[int, str]:
        self._throttle()
        resp = self._session.get(url, timeout=self.timeout)
        if resp.status_code == 429:
            log.warning("OLX 429 on %s", url[:60])
            time.sleep(random.uniform(5, 10))
            raise ConnectionError(f"429 on {url}")
        return resp.status_code, resp.text

    def close(self) -> None: self._session.close()

class RieltorHttpClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
        })
        self._last_req: float = 0
        self._min_delay = 8.0                            

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed + random.uniform(0.3, 1.0))
        self._last_req = time.time()

    @retry(max_attempts=3, base_delay=5.0)
    def get(self, url: str) -> tuple[int, str]:
        self._throttle()
        resp = self._client.get(url)
        if resp.status_code == 429:
            log.warning("Rieltor 429 on %s", url[:60])
            time.sleep(random.uniform(10, 20))
            raise ConnectionError(f"429 on {url}")
        return resp.status_code, resp.text

    def close(self) -> None: self._client.close()
