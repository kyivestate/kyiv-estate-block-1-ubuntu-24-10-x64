"""Rieltor.ua parser v2 — DEFINITIVE extraction using real CSS class structure.
All data from: offer-view-price-title, offer-view-details-row, offer-view-region,
offer-view-address, offer-view-rieltor-*, offer-view-labels, og:description fallback."""
from __future__ import annotations
import re, json
from bs4 import BeautifulSoup, NavigableString
from parser_v2.models.listing import RawListing
from parser_v2.services.http_client import RieltorHttpClient
from parser_v2.services.kyiv_region import is_kyiv_city, is_kyiv_region
from parser_v2.utils.text import content_hash, clean_text
from parser_v2.services.logging_setup import get_logger
log = get_logger("rieltor_parser")
RIELTOR_BASE = "https://rieltor.ua"

class RieltorParser:
    def __init__(self, http: RieltorHttpClient, operation: str, max_pages: int = 999, property_types: set[str] | None = None,
                 geographic_scope: str = "kyiv"):
        self.http = http; self.operation = operation; self.max_pages = max_pages
        if geographic_scope not in {"kyiv", "kyiv_region"}:
            raise ValueError("geographic_scope must be kyiv or kyiv_region")
        self.geographic_scope = geographic_scope
        self.http._min_delay = 5.0
        suffix = "rent" if operation == "rent" else "sale"
        all_base_urls = [
            (f"{RIELTOR_BASE}/flats-{suffix}/", "Квартира"),
            (f"{RIELTOR_BASE}/houses-{suffix}/", "Будинок"),
        ]
        self.base_urls = [item for item in all_base_urls if property_types is None or item[1] in property_types]
        self._property_by_url = {}

    def collect_listing_urls(self) -> list[dict[str, str]]:
        results, seen = [], set()
        for base_url, property_type in self.base_urls:
            empty_streak = 0
            for page in range(1, self.max_pages + 1):
                url = base_url if page == 1 else f"{base_url}?page={page}"
                try:
                    status, html = self.http.get(url)
                    if status == 404:
                        log.info("Rieltor %s p%d: end", property_type, page)
                        break
                    if status != 200:
                        log.warning("Rieltor %s p%d: HTTP %d", property_type, page, status)
                        break
                    count = 0
                    for match in re.finditer(r'https://rieltor\.ua/(?:flats|houses)-(?:rent|sale)/view/(\d+)/', html):
                        href = match.group(0)
                        if href in seen:
                            continue
                        seen.add(href)
                        self._property_by_url[href] = property_type
                        results.append({"url": href, "external_id": f"rieltor_{match.group(1)}"})
                        count += 1
                    log.info("Rieltor %s p%d: %d new (total %d)", property_type, page, count, len(results))
                    if count == 0:
                        empty_streak += 1
                        if empty_streak >= 2:
                            break
                    else:
                        empty_streak = 0
                except Exception as exc:
                    log.error("Rieltor %s p%d error: %s", property_type, page, exc)
                    break
        log.info("Rieltor collected %d URLs for %s", len(results), self.operation)
        return results

    def fetch_and_parse(self, url: str, external_id: str) -> tuple[RawListing, dict]:
        raw = RawListing(source="rieltor", operation=self.operation, external_id=external_id, url=url)
        try:
            status, html = self.http.get(url)
            raw.http_status = status; raw.content_hash = content_hash(html)
            if status in (404, 410):
                raw.parse_status = "failed"; raw.error_message = f"HTTP {status}"; return raw, {}
            if status != 200:
                raw.parse_status = "failed"; raw.error_message = f"HTTP {status}"; return raw, {}
            raw.raw_html = html
            extracted = self._extract(html, url)
            location_text = " ".join(str(extracted.get(key, "")) for key in ("city", "address", "title"))
            in_scope = is_kyiv_region(location_text) if self.geographic_scope == "kyiv_region" else is_kyiv_city(location_text)
            if not in_scope:
                raw.parse_status = "filtered"
                raw.error_message = f"outside_{self.geographic_scope}:{clean_text(extracted.get('city', '')) or 'unknown'}"
                return raw, {}
            extracted["property_type"] = self._property_by_url.get(url, "Квартира")
            raw.parse_status = "parsed"
            return raw, extracted
        except Exception as e:
            raw.parse_status = "failed"; raw.error_message = str(e)[:500]; return raw, {}

    def _b_val(self, soup: BeautifulSoup, label: str) -> str:
        for b in soup.find_all("b"):
            if label.lower() in b.get_text().lower():
                nxt = b.next_sibling
                while nxt:
                    if isinstance(nxt, NavigableString):
                        t = nxt.strip()
                        if t: return t
                    elif hasattr(nxt, 'get_text'):
                        t = nxt.get_text().strip()
                        if t: return t
                    nxt = nxt.next_sibling
                if b.parent:
                    parts = b.parent.get_text().split(b.get_text())
                    if len(parts) > 1: return parts[1].strip()
        return ""

    def _extract(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml"); d: dict = {"url": url}

                                            
        pe = soup.select_one("div.offer-view-price-title")
        if pe: d["price_raw"] = clean_text(pe.get_text())
        if not d.get("price_raw"):
            pe2 = soup.select_one("div.offer-view-price")
            if pe2: d["price_raw"] = clean_text(pe2.get_text())

                                                                
        addr_el = soup.select_one("div.offer-view-address")
        if addr_el: d["street"] = clean_text(addr_el.get_text())

        addr_line = soup.select_one("div.offer-view-address-line")
        if addr_line: d["address"] = clean_text(addr_line.get_text())

        region_el = soup.select_one("div.offer-view-region")
        if region_el:
            region_text = clean_text(region_el.get_text())
                                                                 
            parts = [p.strip() for p in region_text.split(",")]
            if parts: d["city"] = parts[0]
            if len(parts) > 1:
                dist = parts[1].replace("р-н", "").replace("район", "").strip()
                d["district"] = dist
                                          
        for a in soup.select("a.address-link"):
            txt = a.get_text().strip()
            if "р-н" in txt:
                d.setdefault("district", txt.replace("р-н", "").strip())
            elif "вул." in txt or "просп." in txt or "бульв." in txt:
                d.setdefault("street", txt)

                                                                        
        detail_rows = soup.select("div.offer-view-details-row")
        for row in detail_rows:
            txt = clean_text(row.get_text()); tl = txt.lower()
                                        
            if "кімнат" in tl:
                m = re.search(r"(\d+)", txt)
                if m: d["rooms"] = m.group(1)
                                                           
            elif "м²" in tl or "м2" in tl:
                m = re.search(r"([\d.,]+)\s*/", txt) or re.search(r"([\d.,]+)\s*м", txt)
                if m: d["area"] = m.group(1).replace(",", ".")
                             
            elif "поверх" in tl:
                m = re.search(r"(\d+)\s*(?:з|із)\s*(\d+)", txt)
                if m: d["floor"] = m.group(1); d["floors_total"] = m.group(2)
                else:
                    m2 = re.search(r"(\d+)", txt)
                    if m2: d["floor"] = m2.group(1)

                                                             
        if not d.get("rooms"):
            v = self._b_val(soup, "Кількість кімнат")
            m = re.search(r"(\d+)", v)
            if m: d["rooms"] = m.group(1)
        if not d.get("area"):
            v = self._b_val(soup, "Загальна площа")
            m = re.search(r"([\d.,]+)", v)
            if m: d["area"] = m.group(1).replace(",", ".")
        if not d.get("floor"):
            v = self._b_val(soup, "Поверх")
            m = re.search(r"(\d+)", v)
            if m: d["floor"] = m.group(1)
        if not d.get("floors_total"):
            v = self._b_val(soup, "Поверховість")
            m = re.search(r"(\d+)", v)
            if m: d["floors_total"] = m.group(1)

                                                               
                                                               
        addr_block = soup.select_one("div.offer-view-address-block, div.offer-view-section.offer-view-address-block")
        if addr_block:
            title_el = addr_block.select_one("div.offer-view-section-title")
            if title_el:
                rc_text = clean_text(title_el.get_text())
                if rc_text and "ЖК" in rc_text:
                    d["residential_complex"] = rc_text.replace("ЖК", "").strip()
                elif rc_text and not any(w in rc_text.lower() for w in ["опис","планування","адрес"]):
                    d["residential_complex"] = rc_text

                                            
        h1 = soup.select_one("h1")
        if h1: d["title"] = clean_text(h1.get_text())
        if not d.get("title"):
            gallery_title = soup.select_one("span.offer-photo-gallery__title")
            if gallery_title: d["title"] = clean_text(gallery_title.get_text())

                                                  
        desc_el = soup.select_one("div.offer-view-section-text")
        if desc_el: d["description"] = clean_text(desc_el.get_text())

                                                      
        name_el = soup.select_one("a.offer-view-rieltor-name")
        if name_el: d["contact_name"] = clean_text(name_el.get_text())

        position_el = soup.select_one("div.offer-view-rieltor-position")
        if position_el:
            pos = clean_text(position_el.get_text()).lower()
            if "власник" in pos: d["agent_type"] = "owner"
            elif "рієлтор" in pos or "ріелтор" in pos or "агент" in pos: d["agent_type"] = "agent"
            else: d["agent_type"] = "agent"

        agency_el = soup.select_one("a.offer-view-rieltor-agency-link")
        if agency_el:
            d["agency_name"] = clean_text(agency_el.get_text())
            d.setdefault("agent_type", "agency")

                
        phones_el = soup.select_one("div.offer-view-rieltor-phones")
        if phones_el:
            phones_text = phones_el.get_text()
            phone_list = re.findall(r"\+?\d[\d\s\(\)\-]{8,}", phones_text)
            if phone_list:
                d["contact_phone"] = phone_list[0].strip()

                                                                               
        labels_el = soup.select_one("div.offer-view-labels")
        if labels_el:
            labels_text = clean_text(labels_el.get_text())
                                       
            m = re.search(r"Комісія\s*([\d]+%?)", labels_text, re.IGNORECASE)
            if m: d["commission"] = f"Комісія {m.group(1)}"
            elif "без комісі" in labels_text.lower(): d["commission"] = "Без комісії"
                                                                                       
            for span in labels_el.select("span, a"):
                txt = span.get_text().strip()
                if txt and "комісі" not in txt.lower() and len(txt) < 40:
                    d.setdefault("metro_station", txt)
                    break

                                              
        photos = []
                             
        for img in soup.select("div.offer-view-gallery img[src], div.offer-photo-gallery img[src]"):
            src = img.get("data-src") or img.get("src") or ""
            if src.startswith("http") and src not in photos: photos.append(src)
                                        
        if not photos:
            for img in soup.select("img[src]"):
                src = img.get("src") or ""
                if "lunstatic" in src and src not in photos: photos.append(src)
        d["photos"] = photos[:20]

                                
        og = soup.find("meta", property="og:image")
        if og: d["photo_url"] = og.get("content", "")
        if not d.get("photo_url") and photos: d["photo_url"] = photos[0]

                                                               
                                                                                      
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            og_text = og_desc.get("content", "")
            if not d.get("price_raw"):
                m = re.match(r"([\d\s]+\s*(?:\$|грн|€|USD|EUR)[^\-]*)", og_text)
                if m: d["price_raw"] = m.group(1).strip()
            if not d.get("rooms"):
                m = re.search(r"(\d+)\s*кімнат", og_text)
                if m: d["rooms"] = m.group(1)
            if not d.get("floor"):
                m = re.search(r"(\d+)\s*поверх\s*(\d+)", og_text)
                if m: d["floor"] = m.group(1); d.setdefault("floors_total", m.group(2))
            if not d.get("area"):
                m = re.search(r"([\d.,]+)\s*/\s*[\d.,]+\s*/\s*[\d.,]+\s*м", og_text)
                if m: d["area"] = m.group(1).replace(",", ".")
                else:
                    m2 = re.search(r"([\d.,]+)\s*м²", og_text)
                    if m2: d["area"] = m2.group(1).replace(",", ".")

                                                              
        desc = d.get("description", "")
        if desc:
            if not d.get("residential_complex"):
                m = re.search(r'(?:ЖК|житлов(?:ий|ому)\s+комплекс[іi]?)\s*[«"\'"]?([^»"\'"\n,.]{2,40})', desc, re.IGNORECASE)
                if m: d["residential_complex"] = m.group(1).strip().rstrip('"\'»')

        return d
