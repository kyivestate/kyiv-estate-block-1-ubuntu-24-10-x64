from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CommercialRawListing:
    source: str
    operation: str
    external_id: str
    url: str
    http_status: int = 0
    raw_html: str = ""
    content_hash: str = ""
    parse_status: str = "pending"
    error_message: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CommercialListing:
    source: str
    operation: str
    external_id: str
    url: str
    commercial_type: str = "multifunctional"
    commercial_subtype: str = ""
    title: str = ""
    description: str = ""
    ai_title: str = ""
    ai_description: str = ""
    price_amount: float | None = None
    price_currency: str = "UNKNOWN"
    price_period: str = "unknown"
    price_uah: float | None = None
    price_usd: float | None = None
    price_eur: float | None = None
    price_per_m2: float | None = None
    price_per_m2_currency: str = "UNKNOWN"
    price_per_m2_uah: float | None = None
    price_per_m2_usd: float | None = None
    price_per_m2_eur: float | None = None
    price_per_m2_period: str = "unknown"
    source_price_raw: str = ""
    vat_included: bool | None = None
    opex_amount: float | None = None
    utilities_included: bool | None = None
    area_total_m2: float | None = None
    area_usable_m2: float | None = None
    floor: int | None = None
    floors_total: int | None = None
    floor_label: str = ""
    ceiling_height_m: float | None = None
    layout_type: str = ""
    condition: str = ""
    fitout: str = ""
    separate_entrance: bool | None = None
    facade: bool | None = None
    showcase_windows: bool | None = None
    parking_spaces: int | None = None
    loading_dock: bool | None = None
    ramp: bool | None = None
    freight_elevator: bool | None = None
    electric_power_kw: float | None = None
    electricity_backup: bool | None = None
    generator: bool | None = None
    water_supply: bool | None = None
    sewerage: bool | None = None
    heating_type: str = ""
    ventilation: bool | None = None
    air_conditioning: bool | None = None
    fire_safety: bool | None = None
    security: bool | None = None
    internet: bool | None = None
    shelter_distance_m: int | None = None
    permitted_use: str = ""
    city: str = "Київ"
    district: str = ""
    street: str = ""
    full_address: str = ""
    address_confidence: str = "unknown"
    advertiser_type: str = "unknown"
    contact_name: str = ""
    agency_name: str = ""
    phones: list[str] = field(default_factory=list)
    commission_text: str = ""
    contact_visibility: str = "unknown"
    photo_url: str = ""
    photos: list[str] = field(default_factory=list)
    extraction_confidence: dict[str, Any] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    raw_listing_id: int | None = None
    parsed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
