"""Geographic policy for new Kyiv city / Kyiv oblast listings.

The policy intentionally works on source location text rather than geocoding:
the source catalogue is authoritative for OLX regional pages, while Rieltor
offers expose a city/region string.  Unknown locations are rejected when a
global Rieltor feed is used, so listings from other oblasts cannot leak in.
"""
from __future__ import annotations

KYIV_CITY_TOKENS = (
    "київ", "киев", "kyiv", "kiev", "голосіїв", "голосеев", "дарниц",
    "деснян", "дніпров", "днепров", "оболон", "печер", "поділ", "подол",
    "святошин", "солом", "шевченк",
)



KYIV_OBLAST_TOKENS = (
    "київська область", "киевская область", "київ обл", "киев обл",
    "біла церква", "белая церковь", "борисп", "бровар", "буч", "васильк",
    "вишгород", "ірпін", "ирпен", "обух", "переяслав", "фастів", "фастов",
    "яготин", "березань", "богуслав", "миронів", "миронов", "рокитн",
    "сквир", "теті", "тетієв", "узин", "славутич", "макар", "згурів",
    "бариш", "іванків", "иванков", "поліськ", "полес", "ставищ", "тарас",
    "володар", "кагар", "гостомел", "ворзель", "козин", "гнідин", "гнедин",
    "вишеньк", "білогород", "белогород", "боярк", "вишнев", "вишнево",
    "крюківщ", "крюковщ", "гатн", "хотів", "хотов", "лесник", "лісник",
    "горенич", "дмитрів", "дмитров", "петрівц", "петровц", "софіївська борщаг",
    "софиевская борщаг", "петропавлівська борщаг", "петропавловская борщаг",
    "щаслив", "гора", "проців", "процев", "ходосів", "ходосов", "тарасів",
    "тарасов", "глевах", "калинів", "калинов", "чабан", "клавдієв", "кладиев",
    "немішаєв", "немешаев", "михайлівка", "михайловка", "погреб", "зазим",
    "лебедів", "лебедев", "пухів", "пухов", "килів", "ржищ",
)


def _clean(text: object) -> str:
    return " ".join(str(text or "").lower().replace("’", "'").split())


def is_kyiv_city(text: object) -> bool:
    value = _clean(text)
    if "київська область" in value or "киевская область" in value:
        return False
    return any(token in value for token in KYIV_CITY_TOKENS)


def is_kyiv_region(text: object) -> bool:
    value = _clean(text)
    return is_kyiv_city(value) or any(token in value for token in KYIV_OBLAST_TOKENS)


def region_city_label(text: object) -> str:
    """Keep the source location at least at city/oblast granularity."""
    return "Київ" if is_kyiv_city(text) else "Київська область"
