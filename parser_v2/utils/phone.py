"""Phone normalization."""
from __future__ import annotations
import re
def normalize_phone(raw: str | None) -> str:
    if not raw: return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10 and digits.startswith("0"): return f"+38{digits}"
    if len(digits) == 12 and digits.startswith("380"): return f"+{digits}"
    return raw.strip()
