"""Multi-source field extraction with confidence scoring."""
from __future__ import annotations
import re
from parser_v2.models.listing import NormalizedListing, RawListing
from parser_v2.services.photo_selection import select_property_photo, select_property_photos
from parser_v2.services.currency import currency_service
from parser_v2.services.address_parser import parse_address
from parser_v2.services.commission import normalize_commission
from parser_v2.utils.text import clean_text, extract_int, extract_price_and_currency
from parser_v2.utils.phone import normalize_phone
from parser_v2.services.logging_setup import get_logger
log = get_logger("normalizer")

def _regex_rooms(text: str) -> int | None:
    m = re.search(r"(\d)\s*-?\s*(?:кімн|комн|к\.?\s)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None

def _regex_area(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м²|кв\.?\s*м|m²|м2)", text, re.IGNORECASE)
    if m:
        try: return float(m.group(1).replace(",", "."))
        except ValueError: pass
    return None

def _regex_floor(text: str) -> tuple[int | None, int | None]:
    floor_marker = r"(?:поверх|этаж|етаж|пов\.?|эт\.?)"
    # Covers both `23/24 поверх` and the common OLX form `23эт/24эт`.
    # The latter previously fell through to an address such as `37/1`,
    # producing impossible floor values in otherwise valid apartments.
    m = re.search(
        rf"(\d{{1,2}})\s*{floor_marker}?\s*/\s*(\d{{1,2}})\s*{floor_marker}",
        text,
        re.IGNORECASE,
    )
    if m: return int(m.group(1)), int(m.group(2))
    m2 = re.search(r"(\d{1,2})\s*(?:поверх|этаж|пов\.)", text, re.IGNORECASE)
    if m2: return int(m2.group(1)), None
    return None, None

def _detect_agent(text: str) -> str:
    tl = text.lower()
    if any(w in tl for w in ("власник","собственник","хозяин","без комісі","без посередник")): return "owner"
    if any(w in tl for w in ("агент","ріелтор","риелтор")): return "agent"
    if any(w in tl for w in ("агентств","компанія","компания")): return "agency"
    return "unknown"


def _property_type_from_content(declared: str, title: str) -> str:
    """Reject OLX promoted cards whose actual type differs from the catalogue.

    OLX may place a promoted house into an apartment search result.  The
    category URL alone is therefore not authoritative for the production
    contour; a house is recognised only from an explicit title signal.
    """
    value = clean_text(declared) or "Квартира"
    if value != "Квартира":
        return value
    # Do not classify ordinary "квартира в будинку" as a house: require an
    # offer-type phrase or a title beginning with a house subtype.
    if re.search(
        r"^\s*(?:будин\w*|котедж\w*|таунхаус\w*|дуплекс\w*)\b|"
        # OLX frequently separates the offer type with `/`, `:` or `-`, e.g.
        # "Оренда / Будинок".  Treat those separators exactly like whitespace,
        # while retaining the offer-type requirement to avoid mistaking an
        # apartment's address such as "будинок 7" for a detached house.
        r"\b(?:оренда|продаж|продається|здам|здається)[\s/:,-]+(?:будин\w*|котедж\w*|таунхаус\w*|дуплекс\w*)\b",
        title,
        re.IGNORECASE,
    ):
        return "Будинок"
    return value

def normalize_listing(raw: RawListing, sd: dict) -> NormalizedListing:
    confidence: dict[str, str] = {}
    title = clean_text(sd.get("title", ""))
    description = clean_text(sd.get("description", ""))
    combined = f"{title} {description}"

    price_raw = sd.get("price_raw", "")
    price_val, price_cur = extract_price_and_currency(price_raw)
    if not price_val: price_val, price_cur = extract_price_and_currency(sd.get("price_text", ""))
    if not price_cur: price_cur = "UAH" if raw.operation == "rent" else "USD"
    price_uah = price_usd = price_eur = None
    if price_val and price_val > 0:
        price_uah, price_usd, price_eur = currency_service.convert(price_val, price_cur)
    confidence["price"] = "structured" if price_val else "missing"

    rooms_s = sd.get("rooms"); rooms_r = _regex_rooms(combined)
    rooms = extract_int(str(rooms_s)) if rooms_s else (rooms_r if rooms_r else None)
    confidence["rooms"] = "structured" if rooms_s else ("regex" if rooms_r else "missing")

    area_s = sd.get("area"); area_r = _regex_area(combined); area = None
    if area_s:
        try: area = float(str(area_s).replace(",", ".").replace("м²", "").strip()); confidence["area"] = "structured"
        except ValueError: area = area_r; confidence["area"] = "regex" if area_r else "missing"
    else: area = area_r; confidence["area"] = "regex" if area_r else "missing"

    floor_s = sd.get("floor"); ft_s = sd.get("floors_total") or sd.get("floor_total")
    floor_r, ft_r = _regex_floor(combined)
    floor = extract_int(str(floor_s)) if floor_s else floor_r
    floor_total = extract_int(str(ft_s)) if ft_s else ft_r
    floor_confidence = "structured" if floor_s else ("regex" if floor_r else "missing")
    # Structured fields in an OLX card can occasionally be polluted by a
    # street number (`37/1`).  Prefer an explicit valid floor pair extracted
    # from the listing body, and never publish a mathematically impossible
    # floor when no reliable replacement exists.
    if floor is not None and floor_total is not None and floor > floor_total:
        if floor_r is not None and ft_r is not None and floor_r <= ft_r:
            floor, floor_total = floor_r, ft_r
            floor_confidence = "regex_override"
        else:
            floor = floor_total = None
            floor_confidence = "invalid"
    confidence["floor"] = floor_confidence

    at_s = sd.get("agent_type", "")
    agent_type = at_s if at_s in ("owner","agent","agency") else _detect_agent(combined)

    addr = parse_address(sd.get("address", ""), sd.get("district", ""), sd.get("street", ""), sd.get("residential_complex", ""))
    photos = select_property_photos(sd.get("photos", []) or [], sd.get("photo_url", ""))
    photo_url = select_property_photo(photos, sd.get("photo_url", ""))

    nl = NormalizedListing(
        source=raw.source, operation=raw.operation, external_id=raw.external_id, url=raw.url,
        property_type=_property_type_from_content(sd.get("property_type", ""), title),
        title=title, description=description,
        price_uah=price_uah, price_usd=price_usd, price_eur=price_eur,
        source_price_raw=price_raw, source_currency=price_cur,
        rooms=rooms, area=area, floor=floor, floor_total=floor_total,
        agent_type=agent_type, contact_name=clean_text(sd.get("contact_name", "")),
        contact_phone=normalize_phone(sd.get("contact_phone", "")),
        commission=normalize_commission(sd.get("commission", ""), combined),
        residential_complex=addr["residential_complex"], city=addr["city"],
        district=addr["district"], street=addr["street"],
        metro_station=clean_text(sd.get("metro_station", "")), full_address=addr["full_address"],
        photo_url=photo_url, photos=photos, extraction_confidence=confidence, parsed_at=raw.fetched_at,
    )
    if not nl.title and not nl.description: nl.validation_errors.append("no_content")
    if not nl.price_uah: nl.validation_errors.append("no_price")
    if nl.validation_errors: nl.is_valid = False
    return nl
