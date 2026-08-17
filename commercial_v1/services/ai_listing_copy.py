from __future__ import annotations

import re


BANNED = re.compile(r"комісі|ріелтор|риелтор|брокер|агент|агентств|власник|собственник|контакт|телефон|дзвон|дзвін|звон|пишіть|звертайтеся|не\s+турбувати|viber|telegram|whatsapp", re.IGNORECASE)
PHONE = re.compile(r"(?:\+?38)?[\s()\-]*0\d(?:[\s()\-]*\d){8,}")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


TYPE_NAMES = {
    "office": ("офісне приміщення", "офісного приміщення"),
    "retail": ("торгове приміщення", "торгового приміщення"),
    "warehouse": ("складське приміщення", "складського приміщення"),
    "industrial": ("виробниче приміщення", "виробничого приміщення"),
    "horeca": ("приміщення для HoReCa", "приміщення для HoReCa"),
    "medical": ("медичне приміщення", "медичного приміщення"),
    "hotel": ("готельний об’єкт", "готельного об’єкта"),
    "building": ("окрема будівля", "окремої будівлі"),
    "multifunctional": ("комерційне приміщення", "комерційного приміщення"),
}


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value: object) -> str:
    try:
        value = float(value)
        return str(int(value)) if value.is_integer() else str(value).replace(".", ",")
    except (TypeError, ValueError):
        return ""


def clean_source(value: object) -> str:
    source = URL.sub("", PHONE.sub("", str(value or "")))
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", source):
        sentence = text(sentence)
        if len(sentence) >= 12 and not BANNED.search(sentence):
            kept.append(sentence)
    return " ".join(kept)[:49000]


def clean_fact(value: object) -> str:
    source = URL.sub("", PHONE.sub("", str(value or "")))
    source = re.sub(r"\b(?:без\s+)?комісі\w*\b[^,.;!?]*", "", source, flags=re.IGNORECASE)
    source = BANNED.sub("", source)
    return text(source).strip(" ,.;:-")


def object_name(row: dict, genitive: bool = False) -> str:
    return TYPE_NAMES.get(text(row.get("commercial_type")).lower(), TYPE_NAMES["multifunctional"])[1 if genitive else 0]


def district_in_locative(value: str) -> str:
    return value[:-2] + "ому" if value.endswith("ий") else value


def build_title(row: dict) -> str:
    action = "Оренда" if row.get("operation") == "rent" else "Продаж"
    parts = [action, object_name(row, genitive=True)]
    area = number(row.get("area_total_m2"))
    district = clean_fact(row.get("district"))
    if area:
        parts.append(f"{area} м²")
    if district:
        parts.append(f"у {district_in_locative(district)} районі")
    return " ".join(parts)[:180]


def build_description(row: dict) -> str:
    action = "в оренду" if row.get("operation") == "rent" else "до продажу"
    area = number(row.get("area_total_m2"))
    first = f"Пропонується {action} {object_name(row)}"
    if area:
        first += f" загальною площею {area} м²"
    sentences = [first + "."]
    location = [value for value in (clean_fact(row.get("district")), clean_fact(row.get("street")), clean_fact(row.get("full_address"))) if value]
    if location:
        sentences.append("Розташування, зазначене в оголошенні: " + ", ".join(dict.fromkeys(location)) + ".")
    floor = number(row.get("floor")) or re.search(r"\d+", clean_fact(row.get("floor_label")) or "")
    floor = floor.group(0) if hasattr(floor, "group") else floor
    total = number(row.get("floors_total"))
    if floor and total:
        sentences.append(f"Поверх: {floor} з {total}.")
    elif floor:
        sentences.append(f"Поверх: {floor}.")
    facts = []
    for label, key in (("Призначення", "permitted_use"), ("Стан", "condition"), ("Планування", "layout_type")):
        value = text(row.get(key))
        if value:
            facts.append(f"{label}: {value}")
    if facts:
        sentences.append("Характеристики: " + "; ".join(facts) + ".")
    details = clean_source(row.get("description"))
    if details:
        sentences.append("Деталі об’єкта: " + details)
    return "\n\n".join(sentences)[:49000]
