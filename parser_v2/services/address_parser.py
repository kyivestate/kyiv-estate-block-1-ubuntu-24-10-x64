"""Address parsing and Kyiv district normalization."""
from __future__ import annotations
import re

KYIV_DISTRICTS = ["Голосіївський","Дарницький","Деснянський","Дніпровський","Оболонський",
    "Печерський","Подільський","Святошинський","Солом'янський","Шевченківський"]
DISTRICT_ALIASES: dict[str, str] = {
    "Голосеевский":"Голосіївський","Дарницкий":"Дарницький","Деснянский":"Деснянський",
    "Днепровский":"Дніпровський","Оболонский":"Оболонський","Печерский":"Печерський",
    "Подольский":"Подільський","Подол":"Подільський","Святошинский":"Святошинський",
    "Соломенский":"Солом'янський","Шевченковский":"Шевченківський",
}

def normalize_district(raw: str) -> str:
    if not raw: return ""
    raw = raw.strip()
    if raw in KYIV_DISTRICTS: return raw
    if raw in DISTRICT_ALIASES: return DISTRICT_ALIASES[raw]
    for d in KYIV_DISTRICTS:
        if d.lower() in raw.lower() or raw.lower() in d.lower(): return d
    for alias, canonical in DISTRICT_ALIASES.items():
        if alias.lower() in raw.lower(): return canonical
    return raw

def parse_address(raw_address: str, raw_district: str = "", raw_street: str = "", raw_rc: str = "") -> dict[str, str]:
    result = {"city": "Київ", "district": normalize_district(raw_district),
              "street": raw_street.strip() if raw_street else "",
              "residential_complex": raw_rc.strip() if raw_rc else "",
              "full_address": raw_address.strip() if raw_address else ""}
    if not result["district"] and raw_address:
        for d in KYIV_DISTRICTS:
            if d.lower() in raw_address.lower(): result["district"] = d; break
        if not result["district"]:
            for alias, canonical in DISTRICT_ALIASES.items():
                if alias.lower() in raw_address.lower(): result["district"] = canonical; break
    if not result["street"] and raw_address:
        m = re.search(r"(?:вул\.|вулиця|ул\.)\s*([^,]+)", raw_address, re.IGNORECASE)
        if m: result["street"] = m.group(1).strip()
    if not result["residential_complex"] and raw_address:
        m = re.search(r'(?:ЖК|жк)\s*[«"\'"]?([^»"\'",]+)', raw_address)
        if m: result["residential_complex"] = m.group(1).strip()
    return result
