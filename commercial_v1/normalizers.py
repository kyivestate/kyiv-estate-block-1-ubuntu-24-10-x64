from __future__ import annotations

import re

from commercial_v1.models import CommercialListing, CommercialRawListing
from commercial_v1.services.ai_listing_copy import build_description, build_title
from parser_v2.services.currency import currency_service
from parser_v2.services.commission import normalize_commission
from parser_v2.services.kyiv_region import is_kyiv_region, region_city_label
from parser_v2.services.photo_selection import select_property_photo, select_property_photos
from parser_v2.utils.phone import normalize_phone
from parser_v2.utils.text import clean_text


KYIV_DISTRICTS = {
    "голосіївський", "голосеевский", "дарницький", "дарницкий", "деснянський",
    "деснянский", "дніпровський", "днепровский", "оболонський", "оболонский",
    "печерський", "печерский", "подільський", "подольский", "святошинський",
    "святошинский", "солом'янський", "соломенский", "шевченківський", "шевченковский",
}


def _num(value: object) -> float | None:
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _first_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return _num(match.group(1)) if match else None


def _area_from_text(text: str, labels: tuple[str, ...] = (), include_generic: bool = True) -> float | None:
    unit = r"(?:м[²2]|m2|кв\.?\s*м)"
    number = r"(\d[\d\s.,]*)"
    patterns = [rf"(?:{'|'.join(labels)})\s*[:=\-]?\s*{number}\s*{unit}"] if labels else []
    if include_generic:
        patterns.extend((
            rf"(?:площа|area|s)\s*[:=\-]?\s*{number}\s*{unit}",
            rf"{number}\s*{unit}",
        ))
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = _num(match.group(1))
            if value is not None and 5 <= value <= 100000:
                return value
    return None


def _areas(source_data: dict, text: str) -> tuple[float | None, float | None]:
    total = _num(source_data.get("area"))
    if total is None or total < 5:
        total = _area_from_text(text, ("загальна площа", "загальна", "повна площа", "площа приміщення"), include_generic=False)
    if total is None or total < 5:
        total = _area_from_text(text)
    usable = _num(source_data.get("area_usable"))
    if usable is None or usable < 5:
        usable = _area_from_text(text, ("корисна площа", "орендна площа", "орендована площа", "робоча площа", "usable", "rentable"), include_generic=False)
    return total, usable


def _bool(text: str, *terms: str) -> bool | None:
    return True if any(term in text.lower() for term in terms) else None


def _commercial_type(text: str) -> str:
    value = text.lower()
    mappings = (
        ("warehouse", ("склад", "логіст", "ангар")),
        ("industrial", ("виробниц", "цех", "промислов")),
        ("horeca", ("ресторан", "кафе", "бар", "ho.re.ca", "кухн")),
        ("medical", ("стоматолог", "клінік", "медичн")),
        ("office", ("офіс", "бізнес-центр", "бц ")),
        ("retail", ("магазин", "торгов", "шоурум", "фасад")),
        ("hotel", ("готел", "hotel")),
        ("building", ("окрема будів", "нежитлова будів")),
    )
    for kind, terms in mappings:
        if any(term in value for term in terms):
            return kind
    return "multifunctional"


def _currency(token: str) -> str:
    value = token.lower()
    return "USD" if value in {"$", "usd"} or value.startswith("дол") else "EUR" if value in {"€", "eur"} else "UAH"


def _price(raw: str, operation: str, area_m2: float | None) -> tuple[float | None, str, str, float | None, str, str]:
    value = clean_text(raw)
    lowered = value.lower()
    period = "month" if any(x in lowered for x in ("/міс", "/ міся", "за міся", "в міся", "на міся", "per month", "/month")) else "day" if any(x in lowered for x in ("/день", "/ день", "за доб", "на доб", "per day")) else "year" if any(x in lowered for x in ("/рік", "/ рік", "за рік", "на рік", "per year")) else "total" if operation == "buy" else "unknown"
    token = r"\$|usd|дол\.?|грн|uah|₴|€|eur"
    suffix = re.compile(rf"(?P<amount>\d[\d\s.,]*)\s*(?P<currency>{token})(?P<rate>\s*(?:/|за\s*)(?:м[²2]|m2|кв\.?\s*м))?", re.IGNORECASE)
    prefix = re.compile(rf"(?P<currency>{token})\s*(?P<amount>\d[\d\s.,]*)(?P<rate>\s*(?:/|за\s*)(?:м[²2]|m2|кв\.?\s*м))?", re.IGNORECASE)
    matches = sorted([*suffix.finditer(value), *prefix.finditer(value)], key=lambda match: match.start())
    if not matches:
        amount = _first_number(value, r"(?:ціна|price)\s*[:\-]?\s*(\d[\d\s.,]*)")
        return amount, "UNKNOWN", period, None, "UNKNOWN", "unknown"
    values = [(amount, _currency(match.group("currency")), bool(match.group("rate"))) for match in matches if (amount := _num(match.group("amount"))) is not None]
    total_value = next(((amount, currency) for amount, currency, is_rate in values if not is_rate), None)
    rate_value = next(((amount, currency) for amount, currency, is_rate in values if is_rate), None)
    if total_value is None and rate_value is None:
        return None, "UNKNOWN", period, None, "UNKNOWN", "unknown"
    if total_value is None and rate_value is not None:
        total_value = (rate_value[0] * area_m2, rate_value[1]) if area_m2 and area_m2 > 0 else (None, rate_value[1])
    if rate_value is None and total_value is not None:
        rate_value = (total_value[0] / area_m2, total_value[1]) if total_value[0] is not None and area_m2 and area_m2 > 0 else (None, total_value[1])
    total_amount, total_currency = total_value
    rate_amount, rate_currency = rate_value
    return total_amount, total_currency, period, rate_amount, rate_currency, period if rate_amount is not None else "unknown"


def price_from_listing(raw: str, title: str, description: str, operation: str, area_m2: float | None) -> tuple[float | None, str, str, float | None, str, str]:
    parsed = _price(raw, operation, area_m2)
    context = f"{title} {description}"
    rate_marker = r"(?:\$|usd|дол\.?|грн|uah|₴|€|eur)\s*(?:/|за\s*)(?:м[²2]|m2|кв\.?\s*м)"
    if re.search(rate_marker, context, re.IGNORECASE):
        contextual = _price(context, operation, area_m2)
        if re.search(rate_marker, raw, re.IGNORECASE):
            return parsed
        total, currency, period, _, _, _ = parsed
        _, _, _, context_rate, context_rate_currency, context_rate_period = contextual
        if context_rate is not None and (total is None or (operation == "rent" and total <= 500)):
            derived_total = context_rate * area_m2 if area_m2 else None
            return derived_total, context_rate_currency, context_rate_period, context_rate, context_rate_currency, context_rate_period
    total, currency, period, per_m2, per_m2_currency, per_m2_period = parsed
    if operation == "rent" and area_m2 and area_m2 >= 50 and total is not None and currency in {"UAH", "USD", "EUR"} and 0 < total <= 500:
        return total * area_m2, currency, period, total, currency, period
    return total, currency, period, per_m2, per_m2_currency, per_m2_period


def _kyiv_status(text: str, source_catalog: str = "") -> tuple[bool, str]:
    if source_catalog == "kyiv_region":
        return True, "kyiv_or_oblast_catalog"
    if is_kyiv_region(text):
        return True, "kyiv_or_oblast"
    return False, "outside_kyiv_region"


def _phones(values: object) -> list[str]:
    source = values if isinstance(values, list) else re.findall(r"\+?\d[\d\s()\-]{8,}", str(values or ""))
    result: list[str] = []
    for item in source:
        phone = normalize_phone(str(item))
        if phone and phone not in result:
            result.append(phone)
    return result


def normalize_commercial(raw: CommercialRawListing, source_data: dict) -> CommercialListing:
    title = clean_text(source_data.get("title", ""))
    description = clean_text(source_data.get("description", ""))
    address = clean_text(source_data.get("address", ""))
    district = clean_text(source_data.get("district", ""))
    street = clean_text(source_data.get("street", ""))
    text = " ".join((title, description, address, district, street))
    in_kyiv, address_confidence = _kyiv_status(text, str(source_data.get("source_catalog", "")))
    area_total, area_usable = _areas(source_data, text)
    price_raw = clean_text(source_data.get("price_raw", ""))
    price_amount, price_currency, price_period, price_per_m2, price_per_m2_currency, per_m2_period = price_from_listing(price_raw, title, description, raw.operation, area_total)
    if price_currency == "UNKNOWN":
        price_raw = f"{title} {description}"
        price_amount, price_currency, price_period, price_per_m2, price_per_m2_currency, per_m2_period = price_from_listing(price_raw, title, description, raw.operation, area_total)
    price_uah = price_usd = price_eur = None
    if price_amount is not None and price_currency in {"UAH", "USD", "EUR"}:
        price_uah, price_usd, price_eur = currency_service.convert(price_amount, price_currency)
    price_per_m2_uah = price_per_m2_usd = price_per_m2_eur = None
    if price_per_m2 is not None and price_per_m2_currency in {"UAH", "USD", "EUR"}:
        price_per_m2_uah, price_per_m2_usd, price_per_m2_eur = currency_service.convert(price_per_m2, price_per_m2_currency)
    floor = _num(source_data.get("floor"))
    floors_total = _num(source_data.get("floors_total"))
    floor_label = clean_text(source_data.get("floor_label", ""))
    if floor is None:
        floor_pair = re.search(r"(?:поверх|этаж)\s*([\-\d]+)\s*(?:з|из|/)?\s*(\d+)?", text, re.IGNORECASE)
        if floor_pair:
            floor_label = floor_pair.group(1)
            if floor_pair.group(1).isdigit():
                floor = float(floor_pair.group(1))
            if floor_pair.group(2):
                floors_total = float(floor_pair.group(2))
    if floor is not None and floors_total is not None and floor > floors_total:
        floor = None
        floors_total = None
        floor_label = ""
    power = _num(source_data.get("electric_power_kw")) or _first_number(text, r"(\d+(?:[.,]\d+)?)\s*(?:квт|kw)")
    ceiling = _num(source_data.get("ceiling_height_m")) or _first_number(text, r"(?:стел[яі]|h)\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*(?:м|m)")
    advertiser_type = clean_text(source_data.get("advertiser_type", "")).lower()
    if advertiser_type not in {"owner", "agent", "agency", "developer"}:
        lowered = text.lower()
        advertiser_type = "owner" if any(x in lowered for x in ("власник", "собственник")) else "agency" if "агентств" in lowered else "agent" if any(x in lowered for x in ("рієлтор", "риелтор", "агент")) else "unknown"
    listing = CommercialListing(
        source=raw.source,
        operation=raw.operation,
        external_id=raw.external_id,
        url=raw.url,
        commercial_type=clean_text(source_data.get("commercial_type", "")) or _commercial_type(text),
        commercial_subtype=clean_text(source_data.get("commercial_subtype", "")),
        title=title,
        description=description,
        price_amount=price_amount,
        price_currency=price_currency,
        price_period=price_period,
        price_uah=price_uah,
        price_usd=price_usd,
        price_eur=price_eur,
        price_per_m2=price_per_m2,
        price_per_m2_currency=price_per_m2_currency,
        price_per_m2_uah=price_per_m2_uah,
        price_per_m2_usd=price_per_m2_usd,
        price_per_m2_eur=price_per_m2_eur,
        price_per_m2_period=per_m2_period,
        source_price_raw=price_raw,
        vat_included=_bool(text, "пдв включ", "з пдв", "с ндс"),
        utilities_included=_bool(text, "комунальні включ", "коммунальные включ"),
        area_total_m2=area_total,
        area_usable_m2=area_usable,
        floor=int(floor) if floor is not None and floor >= 0 else None,
        floors_total=int(floors_total) if floors_total is not None and floors_total > 0 else None,
        floor_label=floor_label,
        ceiling_height_m=ceiling,
        layout_type=clean_text(source_data.get("layout_type", "")),
        condition=clean_text(source_data.get("condition", "")),
        fitout=clean_text(source_data.get("fitout", "")),
        separate_entrance=_bool(text, "окремий вхід", "отдельный вход"),
        facade=_bool(text, "фасад", "фасадн"),
        showcase_windows=_bool(text, "вітрин", "витрин"),
        loading_dock=_bool(text, "док", "погрузочн"),
        ramp=_bool(text, "рамп"),
        freight_elevator=_bool(text, "вантажн", "грузов"),
        electric_power_kw=power,
        electricity_backup=_bool(text, "резервне живлення", "резервное питание"),
        generator=_bool(text, "генератор"),
        water_supply=_bool(text, "водопостач", "водоснабж"),
        sewerage=_bool(text, "каналіза", "канализац"),
        heating_type=clean_text(source_data.get("heating_type", "")),
        ventilation=_bool(text, "вентиляц"),
        air_conditioning=_bool(text, "кондиціон", "кондицион"),
        fire_safety=_bool(text, "пожежн", "пожарн"),
        security=_bool(text, "охорон", "сигналіза", "сигнализац"),
        internet=_bool(text, "інтернет", "интернет"),
        permitted_use=clean_text(source_data.get("permitted_use", "")),
        city=region_city_label(text),
        district=district,
        street=street,
        full_address=address or street,
        address_confidence=address_confidence,
        advertiser_type=advertiser_type,
        contact_name=clean_text(source_data.get("contact_name", "")),
        agency_name=clean_text(source_data.get("agency_name", "")),
        phones=_phones(source_data.get("phones") or source_data.get("contact_phone")),
        commission_text=normalize_commission(source_data.get("commission", ""), text),
        contact_visibility="public" if source_data.get("phones") or source_data.get("contact_phone") else "unknown",
        photo_url=select_property_photo(source_data.get("photos", []), source_data.get("photo_url", "")),
        photos=select_property_photos(source_data.get("photos", []), source_data.get("photo_url", ""))[:30],
        extraction_confidence={"address": address_confidence, "price": "source" if price_amount is not None else "missing", "area": "source" if area_total is not None else "missing"},
        parsed_at=raw.fetched_at,
    )
    listing.ai_title = build_title(listing.__dict__)
    listing.ai_description = build_description(listing.__dict__)
    if not in_kyiv:
        listing.validation_errors.append("outside_kyiv_region")
    if not title and not description:
        listing.validation_errors.append("no_content")
    if area_total is None:
        listing.validation_errors.append("missing_area")
    return listing
