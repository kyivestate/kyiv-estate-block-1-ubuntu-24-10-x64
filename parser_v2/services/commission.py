"""Conservative commission extraction shared by apartments, houses and commercial.

The public source may use Ukrainian or Russian wording and may expose the
amount either as a structured label or only inside the listing text.  We
normalize only what is explicitly stated; absence is represented consistently
as ``Не вказано`` and never guessed from the advertiser type.
"""
from __future__ import annotations

import re

UNKNOWN = "Не вказано"
PENDING = "Комісія: умови уточнюються"

_SPACE = re.compile(r"\s+")
_NO_COMMISSION = re.compile(r"\b(?:без|безо)\s+(?:будь[- ]?якої\s+)?(?:комісі\w*|комисс\w*|посередник\w*)", re.I)
_TERM = r"(?:комісі\w*|комисс\w*|(?:агентськ\w*|агенці\w*)\s+послуг\w*|послуг\w*\s+(?:агентств\w*|агенці\w*)|рі[еє]лторськ\w*\s+послуг\w*|брокерськ\w*\s+послуг\w*)"
_PERCENT = re.compile(rf"{_TERM}.{{0,42}}?(\d{{1,3}}(?:[.,]\d+)?)\s*(?:%|відсот(?:ок|ків)|процент\w*)", re.I)
_PERCENT_REVERSE = re.compile(rf"(\d{{1,3}}(?:[.,]\d+)?)\s*(?:%|відсот(?:ок|ків)|процент\w*).{{0,42}}?{_TERM}", re.I)
_MONEY = re.compile(rf"{_TERM}.{{0,42}}?(\d[\d\s]{{0,12}}(?:[.,]\d{{1,2}})?)\s*(грн|₴|uah|usd|\$|дол(?:ар\w*)?|€|eur|євро)", re.I)
_BARE_STRUCTURED = re.compile(rf"^\s*{_TERM}\s*[:=\-]?\s*(\d{{1,3}}(?:[.,]\d+)?)\s*$", re.I)
_HAS_TERM = re.compile(_TERM, re.I)


def _number(value: str) -> str:
    numeric = float(value.replace(" ", "").replace(",", "."))
    return str(int(numeric)) if numeric.is_integer() else ("%g" % numeric).replace(".", ",")


def _currency(value: str) -> str:
    value = value.lower()
    if value in {"грн", "₴", "uah"}:
        return "грн"
    if value in {"$", "usd"} or value.startswith("дол"):
        return "$"
    return "€"


def _extract(text: str) -> str | None:
    if not text:
        return None
    text = _SPACE.sub(" ", str(text)).strip()
    if _NO_COMMISSION.search(text):
        return "Без комісії"
    for regex in (_PERCENT, _PERCENT_REVERSE):
        match = regex.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            if value == 0:
                return "Без комісії"
            if 0 < value <= 100:
                return f"Комісія {_number(match.group(1))}%"
    for regex in (_MONEY,):
        match = regex.search(text)
        if match:
            value = float(match.group(1).replace(" ", "").replace(",", "."))
            if value > 0:
                return f"Комісія {_number(match.group(1))} {_currency(match.group(2))}"
    # Rieltor's structured label often sends "Комісія 2" without a percent
    # sign.  This rule is restricted to a field containing nothing else.
    match = _BARE_STRUCTURED.match(text)
    if match:
        value = float(match.group(1).replace(",", "."))
        if value == 0:
            return "Без комісії"
        if 0 < value <= 100:
            return f"Комісія {_number(match.group(1))}%"
    return PENDING if _HAS_TERM.search(text) else None


def normalize_commission(value: object = "", text: object = "") -> str:
    """Return a display-safe, evidence-based commission status.

    A structured value has priority over prose; otherwise the title and
    description are scanned.  We never turn an absent value into a fee.
    """
    structured = _extract(str(value or ""))
    if structured:
        return structured
    from_text = _extract(str(text or ""))
    return from_text or UNKNOWN
