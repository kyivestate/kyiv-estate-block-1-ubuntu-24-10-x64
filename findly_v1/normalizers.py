"""Pure Findly payload normalization; unknown source values remain unknown."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


def text(value: Any, limit: int = 49_000) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def number(value: Any) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        result = Decimal(str(value).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None
    return result if result >= 0 else None


def integer(value: Any) -> int | None:
    result = number(value)
    if result is None or result != result.to_integral_value():
        return None
    return int(result)


def nested_name(value: Any) -> str:
    return text(value.get('name')) if isinstance(value, dict) else text(value)


def photo_urls(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text(item.get('src') or item.get('url'), 2_000) for item in value if isinstance(item, dict) and text(item.get('src') or item.get('url'))]


def origin_source(photos: Any) -> str:
    urls = ' '.join(photo_urls(photos)).lower()
    if 'olx' in urls:
        return 'findly_olx'
    if 'rieltor' in urls:
        return 'findly_rieltor'
    return 'findly'


def normalize(item: dict[str, Any], operation: str) -> dict[str, Any]:
    """Map only explicitly present API data to a stable production record."""
    currency = text(item.get('currency')).upper()
    price = number(item.get('price'))
    photos = photo_urls(item.get('photos'))
    item_id = text(item.get('id'), 200)
    city = nested_name(item.get('city'))
    property_type = nested_name(item.get('property_type') or item.get('type') or item.get('category'))
    latitude, longitude = number(item.get('lat') or item.get('latitude')), number(item.get('lng') or item.get('longitude'))
    errors: list[str] = []
    if not item_id:
        errors.append('missing external id')
    if price is None or price == 0:
        errors.append('missing or invalid price')
    floor, floors_total = integer(item.get('floor')), integer(item.get('total_floors') or item.get('floors_total'))
    if floor is not None and floors_total is not None and floor > floors_total:
        floor = floors_total = None
        errors.append('invalid floor pair cleared')
    values = {
        'source': 'findly', 'operation': operation, 'external_id': item_id,
        'origin_source': origin_source(item.get('photos')), 'url': f'https://findly.com.ua/properties/{item_id}',
        'title': text(item.get('title'), 300), 'description': text(item.get('description')),
        'property_type': property_type, 'source_price_raw': text(item.get('price'), 100), 'source_currency': currency,
        'price_uah': price if currency == 'UAH' else None, 'price_usd': price if currency == 'USD' else None,
        'price_eur': price if currency == 'EUR' else None, 'rooms': integer(item.get('rooms')), 'area': number(item.get('area')),
        'floor': floor, 'floors_total': floors_total, 'district': nested_name(item.get('district')), 'city': city,
        'street': text(item.get('street'), 300), 'full_address': text(item.get('address'), 500),
        'latitude': latitude, 'longitude': longitude, 'photos': photos, 'photo_url': photos[0] if photos else '',
        'contact_name': text(item.get('contact_name') or item.get('owner_name'), 300), 'contact_phone': '',
        'commission': text(item.get('commission'), 300),
        'extraction_confidence': {'source_payload': True}, 'is_valid': not errors, 'validation_errors': errors,
    }
    return values
