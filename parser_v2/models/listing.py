"""Listing data models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class RawListing:
    source: str; operation: str; external_id: str; url: str
    http_status: int = 0; raw_html: str = ""; raw_json: str = ""
    content_hash: str = ""; parse_status: str = "pending"
    error_message: str = ""; retry_count: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class NormalizedListing:
    source: str; operation: str; external_id: str; url: str
    property_type: str = "Квартира"
    title: str = ""; description: str = ""
    price_uah: float | None = None; price_usd: float | None = None; price_eur: float | None = None
    source_price_raw: str = ""; source_currency: str = ""
    rooms: int | None = None; area: float | None = None
    floor: int | None = None; floor_total: int | None = None
    agent_type: str = "unknown"; contact_name: str = ""; contact_phone: str = ""
    commission: str = ""; residential_complex: str = ""
    city: str = "Київ"; district: str = ""; street: str = ""; metro_station: str = ""; full_address: str = ""
    photo_url: str = ""; photos: list[str] = field(default_factory=list)
    cdn_photo_url: str = ""; cdn_photos: list[str] = field(default_factory=list)
    sheet_image_formula: str = ""
    extraction_confidence: dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True; validation_errors: list[str] = field(default_factory=list)
    raw_listing_id: int | None = None
    parsed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def passes_price_filter(self, rent_min_uah: int = 20000, sale_min_usd: int = 60000) -> bool:
        if self.operation == "rent":
            return self.price_uah is not None and self.price_uah >= rent_min_uah
        if self.operation == "buy":
            return self.price_usd is not None and self.price_usd >= sale_min_usd
        return False
