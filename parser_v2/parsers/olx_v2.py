"""OLX parser v2 — curl_cffi Chrome impersonation, multi-source extraction."""
from __future__ import annotations
import re, json
from bs4 import BeautifulSoup
from parser_v2.models.listing import RawListing
from parser_v2.services.http_client import OlxHttpClient
from parser_v2.utils.text import content_hash, clean_text
from parser_v2.services.logging_setup import get_logger
log = get_logger("olx_parser")
OLX_BASE = "https://www.olx.ua"
OLX_URLS = {
    "rent": [
        (f"{OLX_BASE}/uk/nedvizhimost/kvartiry/dolgosrochnaya-arenda-kvartir/kiev/", "Квартира"),
        (f"{OLX_BASE}/uk/nedvizhimost/doma/arenda-domov/kiev/", "Будинок"),
        (f"{OLX_BASE}/uk/nedvizhimost/doma/arenda-domov/ko/", "Будинок"),
    ],
    "buy": [
        (f"{OLX_BASE}/uk/nedvizhimost/kvartiry/prodazha-kvartir/kiev/", "Квартира"),
        (f"{OLX_BASE}/uk/nedvizhimost/doma/prodazha-domov/kiev/", "Будинок"),
        (f"{OLX_BASE}/uk/nedvizhimost/doma/prodazha-domov/ko/", "Будинок"),
    ],
}

class OlxParser:
    def __init__(self, http: OlxHttpClient, operation: str, max_pages: int = 25, property_types: set[str] | None = None):
        self.http = http; self.operation = operation; self.max_pages = max_pages
        self.base_urls = [item for item in OLX_URLS[operation] if property_types is None or item[1] in property_types]
        self._property_by_url: dict[str, str] = {}

    def collect_listing_urls(self) -> list[dict[str, str]]:
        results, seen = [], set()
        for base_url, property_type in self.base_urls:
            for page in range(1, self.max_pages + 1):
                try:
                    status, html = self.http.get(f"{base_url}?page={page}")
                    if status != 200: break
                    soup = BeautifulSoup(html, "lxml")
                    cards = soup.select('div[data-cy="l-card"] a[href]') or soup.select('a[href*="/d/uk/obyavlenie/"]')
                    if not cards: break
                    cnt = 0
                    for card in cards:
                        href = card.get("href", "")
                        if not href.startswith("http"): href = OLX_BASE + href
                        if "/d/uk/" not in href or href in seen: continue
                        seen.add(href); self._property_by_url[href] = property_type
                        results.append({"url": href, "external_id": self._id(href)}); cnt += 1
                    log.info("OLX %s p%d: %d found (total %d)", property_type, page, cnt, len(results))
                    if cnt == 0: break
                except Exception as e: log.error("OLX %s p%d error: %s", property_type, page, e); break
        return results

    def fetch_and_parse(self, url: str, external_id: str) -> tuple[RawListing, dict]:
        raw = RawListing(source="olx", operation=self.operation, external_id=external_id, url=url)
        try:
            status, html = self.http.get(url)
            raw.http_status = status; raw.content_hash = content_hash(html)
            if status != 200: raw.parse_status = "failed"; raw.error_message = f"HTTP {status}"; return raw, {}
            raw.raw_html = html; raw.parse_status = "parsed"
            extracted = self._extract(html, url)
            extracted["property_type"] = self._property_by_url.get(url, "Квартира")
            return raw, extracted
        except Exception as e:
            raw.parse_status = "failed"; raw.error_message = str(e)[:500]; return raw, {}

    def _extract(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml"); d: dict = {"url": url}
                 
        for s in soup.select('script[type="application/ld+json"]'):
            try:
                ld = json.loads(s.string or "")
                if isinstance(ld, dict) and ld.get("@type") == "Product":
                    d["title"] = ld.get("name", ""); d["description"] = ld.get("description", "")
                    offers = ld.get("offers", {})
                    if isinstance(offers, dict): d["price_raw"] = str(offers.get("price", ""))
                    imgs = ld.get("image", [])
                    if isinstance(imgs, list): d["photos"] = [i for i in imgs if isinstance(i, str)]
            except (json.JSONDecodeError, TypeError): pass
              
        for tag, key in [("og:title", "title"), ("og:image", "photo_url")]:
            el = soup.find("meta", property=tag)
            if el: d.setdefault(key, el.get("content", ""))
        md = soup.find("meta", attrs={"name": "description"})
        if md: d.setdefault("description", md.get("content", ""))
            
        h1 = soup.select_one("h1")
        if h1: d.setdefault("title", clean_text(h1.get_text()))
               
        pe = soup.select_one('h3[class*="price"]') or soup.select_one('div[data-testid="ad-price-container"] h3')
        if pe: d.setdefault("price_raw", clean_text(pe.get_text()))
        if not d.get("price_raw"):
            pe2 = soup.find("span", string=re.compile(r"грн|uah|\$|€", re.IGNORECASE))
            if pe2: d["price_raw"] = clean_text(pe2.get_text())
                
        for p in soup.select('li[class*="param"] p, ul[class*="params"] li, p.css-odhutu, [data-testid*="parameter"] p'):
            t = clean_text(p.get_text()); tl = t.lower()
            if "кімнат" in tl or "комнат" in tl:
                m = re.search(r"(\d+)", t)
                if m: d.setdefault("rooms", m.group(1))
            elif "загальна площа" in tl or "площа:" in tl or "м²" in tl:
                m = re.search(r"([\d.,]+)", t)
                if m: d.setdefault("area", m.group(1))
            elif "поверховість" in tl or "этажность" in tl:
                m = re.search(r"(\d+)", t)
                if m: d.setdefault("floors_total", m.group(1))
            elif "поверх" in tl or "этаж" in tl:
                m = re.search(r"(\d+)\s*/\s*(\d+)", t)
                if m: d.setdefault("floor", m.group(1)); d.setdefault("floors_total", m.group(2))
                else:
                    m = re.search(r"(\d+)", t)
                    if m: d.setdefault("floor", m.group(1))
                     
        db = soup.select_one('div[data-cy="ad_description"] div') or soup.select_one('div[class*="description"]')
        if db:
            fd = clean_text(db.get_text())
            if len(fd) > len(d.get("description", "")): d["description"] = fd
                  
        le = soup.select_one('a[href*="map"] span') or soup.select_one('p[class*="location"]')
        if le: d["address"] = clean_text(le.get_text())

        location_context = " ".join(value for value in (d.get("title", ""), d.get("address", "")) if value)
        context = " ".join(value for value in (location_context, d.get("description", "")) if value)
        if not d.get("district"):
            districts = {
                "Голосіївський": ("голосіїв", "голосеев"), "Дарницький": ("дарниц",),
                "Деснянський": ("деснян",), "Дніпровський": ("дніпров", "днепров"),
                "Оболонський": ("оболон",), "Печерський": ("печер",),
                "Подільський": ("поділ", "подол"), "Святошинський": ("святошин",),
                "Солом'янський": ("солом", "соломен"), "Шевченківський": ("шевченк",),
            }
            lowered = context.lower()
            for district, aliases in districts.items():
                if any(alias in lowered for alias in aliases):
                    d["district"] = district
                    break
        street_value = clean_text(d.get("street", ""))
        if len(street_value) < 4 or len(street_value) > 160 or re.search(r"знаход|безкоштов|квартир|будинок|поверх|адреса", street_value, re.IGNORECASE):
            d.pop("street", None)
        if not d.get("street"):
            match = re.search(r"(?:вул(?:иця)?\.?|ул\.?|просп(?:ект)?\.?|бульв(?:ар)?\.?|пров(?:улок)?\.?)\s*([^,\n|/]{3,80})", location_context, re.IGNORECASE)
            if match: d["street"] = clean_text(match.group(1)).rstrip(".")
        metro_stations = (
                "Академмістечко", "Арсенальна", "Берестейська", "Бориспільська", "Васильківська",
                "Видубичі", "Вирлиця", "Виставковий центр", "Вокзальна", "Героїв Дніпра", "Гідропарк",
                "Голосіївська", "Дарниця", "Деміївська", "Дніпро", "Дорогожичі", "Житомирська",
                "Золоті ворота", "Звіринецька", "Іподром", "Кловська", "Контрактова площа", "Либідська",
                "Лісова", "Лівобережна", "Лук'янівська", "Майдан Незалежності", "Мінська", "Нивки",
                "Оболонь", "Олімпійська", "Осокорки", "Палац Україна", "Палац спорту", "Печерська",
                "Площа Українських Героїв", "Площа Льва Толстого", "Поштова площа", "Почайна", "Проспект Берестейський",
                "Славутич", "Сирець", "Тараса Шевченка", "Театральна", "Теремки", "Університет",
                "Харківська", "Хрещатик", "Чернігівська", "Червоний хутір", "Шулявська",
            )
        if d.get("metro_station") and clean_text(d["metro_station"]) not in metro_stations:
            d.pop("metro_station", None)
        if not d.get("metro_station"):
            lowered = context.lower()
            for station in metro_stations:
                if station.lower() in lowered:
                    d["metro_station"] = station
                    break
        for field, maximum in (("rooms", 30), ("floor", 120), ("floors_total", 120)):
            if d.get(field):
                try:
                    if not 1 <= int(float(str(d[field]))) <= maximum:
                        d.pop(field, None)
                except (TypeError, ValueError):
                    d.pop(field, None)
        if d.get("floor") and d.get("floors_total") and int(float(d["floor"])) > int(float(d["floors_total"])):
            d.pop("floor", None)
            d.pop("floors_total", None)
                         
        if not d.get("photos"):
            d["photos"] = [i.get("src","") for i in soup.select('div[class*="photo"] img[src], div[class*="swiper"] img[src]') if i.get("src","").startswith("http")][:20]
                 
        ue = soup.select_one('div[class*="user-info"] a, h4[class*="seller"]')
        if ue: d["contact_name"] = clean_text(ue.get_text())
        return d

    @staticmethod
    def _id(url: str) -> str:
        m = re.search(r"ID([a-zA-Z0-9]+)\.html", url)
        if m: return f"olx_{m.group(1)}"
        m2 = re.search(r"-(\d+)\.html", url)
        if m2: return f"olx_{m2.group(1)}"
        return f"olx_{hash(url) % 10**10}"
