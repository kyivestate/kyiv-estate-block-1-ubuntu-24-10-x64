from __future__ import annotations

import re


REJECTED = re.compile(r"(?:avatars?|profile|userpic|agent[-_]?photo|realtor[-_]?avatar|logo|brand|placeholder|default[-_]?image|120/120|120x120)", re.IGNORECASE)
PROPERTY = re.compile(r"(?:/offers/|offers/|houses-photos|market-images|apollo\.olxcdn\.com|/gallery/|/listing)", re.IGNORECASE)
URL = re.compile(r"https?://[^\s,]+", re.IGNORECASE)


def clean_photo_url(value: object) -> str:
    """Extract one real URL from an ``srcset`` or a normal image attribute."""
    text = str(value or "").strip()
    match = URL.search(text)
    return match.group(0).rstrip(".,;)") if match else ""


def select_property_photos(values: object, preferred: object = "") -> list[str]:
    candidates: list[str] = []
    for value in [preferred, *(values if isinstance(values, (list, tuple)) else [])]:
        url = clean_photo_url(value)
        if url.startswith("http") and url not in candidates:
            candidates.append(url)
    ranked = []
    for index, url in enumerate(candidates):
        score = 0
        if PROPERTY.search(url):
            score += 100
        rejected = bool(REJECTED.search(url))
        ranked.append((score, index, url, rejected))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, _, url, rejected in ranked if not rejected]


def select_property_photo(values: object, preferred: object = "") -> str:
    photos = select_property_photos(values, preferred)
    return photos[0] if photos else ""
