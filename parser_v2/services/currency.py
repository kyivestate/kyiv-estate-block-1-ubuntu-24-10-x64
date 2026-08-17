"""Currency conversion via Monobank API with TTL cache and fallback."""
from __future__ import annotations
import time
import httpx
from parser_v2.config import cfg
from parser_v2.services.logging_setup import get_logger
log = get_logger("currency")

class CurrencyService:
    ISO_USD, ISO_EUR, ISO_UAH = 840, 978, 980
    def __init__(self) -> None:
        self._rates: dict[str, float] = {}
        self._fetched_at: float = 0
        self._ttl = cfg.currency.cache_ttl_seconds

    def _fetch_rates(self) -> None:
        try:
            resp = httpx.get(cfg.currency.api_url, timeout=10)
            if resp.status_code == 200:
                for item in resp.json():
                    if item.get("currencyCodeA") == self.ISO_USD and item.get("currencyCodeB") == self.ISO_UAH:
                        self._rates["USD_UAH"] = float(item.get("rateSell") or item.get("rateBuy") or item.get("rateCross", 0))
                    if item.get("currencyCodeA") == self.ISO_EUR and item.get("currencyCodeB") == self.ISO_UAH:
                        self._rates["EUR_UAH"] = float(item.get("rateSell") or item.get("rateBuy") or item.get("rateCross", 0))
                if self._rates.get("USD_UAH") and self._rates.get("EUR_UAH"):
                    self._fetched_at = time.time()
                    log.info("Rates: USD/UAH=%.2f EUR/UAH=%.2f", self._rates["USD_UAH"], self._rates["EUR_UAH"])
                    return
        except Exception as e:
            log.warning("Currency API failed: %s", e)
        self._rates = {"USD_UAH": cfg.currency.fallback_usd_uah, "EUR_UAH": cfg.currency.fallback_eur_uah}
        self._fetched_at = time.time()
        log.info("Using fallback rates: USD/UAH=%.2f EUR/UAH=%.2f", self._rates["USD_UAH"], self._rates["EUR_UAH"])

    def _ensure(self) -> None:
        if not self._rates or (time.time() - self._fetched_at > self._ttl): self._fetch_rates()

    def convert(self, amount: float, from_currency: str) -> tuple[float, float, float]:
        """Returns (UAH, USD, EUR) all rounded to whole numbers."""
        self._ensure()
        usd_uah = self._rates.get("USD_UAH", cfg.currency.fallback_usd_uah)
        eur_uah = self._rates.get("EUR_UAH", cfg.currency.fallback_eur_uah)
        fc = from_currency.upper()
        if fc == "UAH":   uah, usd, eur = amount, amount / usd_uah, amount / eur_uah
        elif fc == "USD":  uah, usd, eur = amount * usd_uah, amount, amount * usd_uah / eur_uah
        elif fc == "EUR":  uah, usd, eur = amount * eur_uah, amount * eur_uah / usd_uah, amount
        else:              uah, usd, eur = amount, amount, amount
        return round(uah), round(usd), round(eur)

currency_service = CurrencyService()
