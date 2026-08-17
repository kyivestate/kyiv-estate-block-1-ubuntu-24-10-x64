from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from commercial_v1.models import CommercialRawListing
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.utils.text import clean_text, content_hash


OLX_BASE = "https://www.olx.ua"
OLX_URLS = {
    "rent": (
        f"{OLX_BASE}/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/kiev/",
        f"{OLX_BASE}/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/ko/",
    ),
    "buy": (
        f"{OLX_BASE}/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/kiev/",
        f"{OLX_BASE}/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/ko/",
    ),
}
RIELTOR_BASE = "https://rieltor.ua"
RIELTOR_URLS = {
    "rent": f"{RIELTOR_BASE}/commercials-rent/",
    "buy": f"{RIELTOR_BASE}/commercials-sale/",
}


def _district(text: str) -> str:
    values = {
        "Голосіївський": ("голосіїв", "голосеев"), "Дарницький": ("дарниц",),
        "Деснянський": ("деснян",), "Дніпровський": ("дніпров", "днепров"),
        "Оболонський": ("оболон",), "Печерський": ("печер",),
        "Подільський": ("поділ", "подол"), "Святошинський": ("святошин",),
        "Солом'янський": ("солом", "соломен"), "Шевченківський": ("шевченк",),
    }
    lowered = text.lower()
    for name, aliases in values.items():
        if any(alias in lowered for alias in aliases):
            return name
    return ""


def _street(text: str) -> str:
    match = re.search(r"(?<![\wіїєґ])((?:вул(?:иця)?\.?|ул\.?|просп(?:ект)?\.?|бульв(?:ар)?\.?|пров(?:улок)?\.?)\s*[^,\n|/()]{2,100})", text, re.IGNORECASE)
    return clean_text(match.group(0)).rstrip(".") if match else ""


def _photos(soup: BeautifulSoup) -> list[str]:
    values: list[str] = []
    for image in soup.select("img[src], img[data-src]"):
        url = image.get("data-src") or image.get("src") or ""
        if url.startswith("http") and url not in values:
            values.append(url)
    return values[:30]


class OlxCommercialParser:
    source = "olx"

    def __init__(self, operation: str, max_pages: int, start_page: int = 1):
        self.operation = operation
        self.max_pages = max_pages
        self.start_page = max(start_page, 1)
        self.http = OlxHttpClient()

    def close(self) -> None:
        self.http.close()

    def collect_listing_urls(self) -> list[dict[str, str]]:
        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for base_url in OLX_URLS[self.operation]:
            for page in range(self.start_page, self.start_page + self.max_pages):
                status, html = self.http.get(f"{base_url}?page={page}")
                if status != 200:
                    break
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select('div[data-cy="l-card"] a[href]') or soup.select('a[href*="/d/uk/obyavlenie/"]')
                added = 0
                for card in cards:
                    url = card.get("href", "")
                    if not url.startswith("http"):
                        url = OLX_BASE + url
                    if "/d/uk/" not in url or url in seen:
                        continue
                    external_id = self._id(url)
                    if not external_id:
                        continue
                    seen.add(url)



                    result.append({"url": url, "external_id": external_id, "source_catalog": "kyiv_region"})
                    added += 1
                if added == 0:
                    break
        return result

    def fetch_and_parse(self, url: str, external_id: str) -> tuple[CommercialRawListing, dict]:
        raw = CommercialRawListing(source=self.source, operation=self.operation, external_id=external_id, url=url)
        try:
            status, html = self.http.get(url)
            raw.http_status, raw.raw_html, raw.content_hash = status, html, content_hash(html)
            if status != 200:
                raw.parse_status, raw.error_message = "failed", f"HTTP {status}"
                return raw, {}
            raw.parse_status = "parsed"
            return raw, self._extract(html, url)
        except Exception as exc:
            raw.parse_status, raw.error_message = "failed", str(exc)[:500]
            return raw, {}

    @staticmethod
    def _id(url: str) -> str:
        match = re.search(r"ID([A-Za-z0-9]+)\.html", url)
        return f"olx_{match.group(1)}" if match else ""

    def _extract(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        data: dict = {"url": url, "photos": _photos(soup)}
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(script.string or "")
            except (TypeError, json.JSONDecodeError):
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                if not isinstance(item, dict) or item.get("@type") != "Product":
                    continue
                data.setdefault("title", item.get("name", ""))
                data.setdefault("description", item.get("description", ""))
                offer = item.get("offers", {})
                if isinstance(offer, dict):
                    data.setdefault("price_raw", str(offer.get("price", "")))
                images = item.get("image", [])
                if isinstance(images, list):
                    data["photos"] = [image for image in images if isinstance(image, str) and image.startswith("http")][:30] or data["photos"]
        h1 = soup.select_one("h1")
        if h1:
            data.setdefault("title", clean_text(h1.get_text()))
        description = soup.select_one('div[data-cy="ad_description"] div, div[class*="description"]')
        if description:
            data["description"] = clean_text(description.get_text())
        price = soup.select_one('h3[class*="price"], div[data-testid="ad-price-container"] h3')
        if price:
            data["price_raw"] = clean_text(price.get_text())
        location = soup.select_one('a[href*="map"] span, p[class*="location"]')
        if location:
            data["address"] = clean_text(location.get_text())
        text = " ".join(str(data.get(key, "")) for key in ("title", "description", "address"))
        data["district"] = _district(text)
        data["street"] = _street(str(data.get("address", ""))) or _street(str(data.get("title", "")))
        for node in soup.select('li[class*="param"] p, ul[class*="params"] li, [data-testid*="parameter"] p'):
            value = clean_text(node.get_text())
            lowered = value.lower()
            if "площа" in lowered or "м²" in lowered or "м2" in lowered:
                match = re.search(r"(\d[\d.,]*)", value)
                if match:
                    data.setdefault("area", match.group(1))
            elif "поверх" in lowered or "этаж" in lowered:
                match = re.search(r"(\d+)\s*/\s*(\d+)", value)
                if match:
                    data["floor"], data["floors_total"] = match.group(1), match.group(2)
                else:
                    data["floor_label"] = value
        seller = soup.select_one('div[class*="user-info"] a, h4[class*="seller"]')
        if seller:
            data["contact_name"] = clean_text(seller.get_text())
        if data["photos"]:
            data["photo_url"] = data["photos"][0]
        return data


class RieltorCommercialParser:
    source = "rieltor"

    def __init__(self, operation: str, max_pages: int, start_page: int = 1):
        self.operation = operation
        self.max_pages = max_pages
        self.start_page = max(start_page, 1)
        self.http = RieltorHttpClient()

    def close(self) -> None:
        self.http.close()

    def collect_listing_urls(self) -> list[dict[str, str]]:
        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for page in range(self.start_page, self.start_page + self.max_pages):
            url = RIELTOR_URLS[self.operation] if page == 1 else f"{RIELTOR_URLS[self.operation]}?page={page}"
            status, html = self.http.get(url)
            if status != 200:
                break
            added = 0
            for match in re.finditer(r"https://rieltor\.ua/commercials-(?:rent|sale)/view/(\d+)/", html):
                href = match.group(0)
                if href in seen:
                    continue
                seen.add(href)
                result.append({"url": href, "external_id": f"rieltor_{match.group(1)}"})
                added += 1
            if added == 0:
                break
        return result

    def fetch_and_parse(self, url: str, external_id: str) -> tuple[CommercialRawListing, dict]:
        raw = CommercialRawListing(source=self.source, operation=self.operation, external_id=external_id, url=url)
        try:
            status, html = self.http.get(url)
            raw.http_status, raw.raw_html, raw.content_hash = status, html, content_hash(html)
            if status != 200:
                raw.parse_status, raw.error_message = "failed", f"HTTP {status}"
                return raw, {}
            raw.parse_status = "parsed"
            return raw, self._extract(html, url)
        except Exception as exc:
            raw.parse_status, raw.error_message = "failed", str(exc)[:500]
            return raw, {}

    def _extract(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        data: dict = {"url": url, "photos": _photos(soup)}
        h1 = soup.select_one("h1, span.offer-photo-gallery__title")
        if h1:
            data["title"] = clean_text(h1.get_text())
        price = soup.select_one("div.offer-view-price-title, div.offer-view-price")
        if price:
            data["price_raw"] = clean_text(price.get_text())
        address = soup.select_one("div.offer-view-address, div.offer-view-address-line")
        if address:
            data["address"] = clean_text(address.get_text())
        region = soup.select_one("div.offer-view-region")
        if region:
            region_text = clean_text(region.get_text())
            data["district"] = _district(region_text)
            data["address"] = " ".join((data.get("address", ""), region_text)).strip()
        text_block = soup.select_one("div.offer-view-section-text")
        if text_block:
            data["description"] = clean_text(text_block.get_text())
        details = " ".join(clean_text(node.get_text()) for node in soup.select("div.offer-view-details-row"))
        text = " ".join((str(data.get("title", "")), str(data.get("description", "")), str(data.get("address", "")), details))
        data.setdefault("district", _district(text))
        data["street"] = _street(str(data.get("address", ""))) or _street(str(data.get("title", "")))
        area = re.search(r"(\d[\d.,]*)\s*(?:м²|м2|m2)", details, re.IGNORECASE)
        if area:
            data["area"] = area.group(1)
        floor = re.search(r"(\d+)\s*(?:з|из|/)\s*(\d+)\s*(?:поверх|этаж)?", details, re.IGNORECASE)
        if floor:
            data["floor"], data["floors_total"] = floor.group(1), floor.group(2)
        name = soup.select_one("a.offer-view-rieltor-name")
        if name:
            data["contact_name"] = clean_text(name.get_text())
        position = soup.select_one("div.offer-view-rieltor-position")
        if position:
            value = clean_text(position.get_text()).lower()
            data["advertiser_type"] = "owner" if "власник" in value else "agent"
        agency = soup.select_one("a.offer-view-rieltor-agency-link")
        if agency:
            data["agency_name"] = clean_text(agency.get_text())
            data["advertiser_type"] = "agency"
        phones = soup.select_one("div.offer-view-rieltor-phones")
        if phones:
            data["phones"] = re.findall(r"\+?\d[\d\s()\-]{8,}", phones.get_text())
        if data["photos"]:
            data["photo_url"] = data["photos"][0]
        return data
