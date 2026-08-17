"""Text extraction utilities."""
from __future__ import annotations
import re, hashlib

def clean_text(s: str | None) -> str:
    if not s: return ""
    return re.sub(r"\s+", " ", s).strip()

def extract_number(s: str | None) -> float | None:
    if not s: return None
    m = re.search(r"[\d]+[.,]?\d*", s.replace("\xa0", "").replace(" ", ""))
    if m:
        try: return float(m.group().replace(",", "."))
        except ValueError: return None
    return None

def extract_int(s: str | None) -> int | None:
    v = extract_number(s)
    return int(v) if v is not None else None

def content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()

def extract_price_and_currency(raw: str) -> tuple[float | None, str]:
    """Parse prices like '45 000 грн/міс', '2 400 $/міс', '95000 $', '1500000 грн'."""
    if not raw: return None, ""

                                              
    currency = ""
    if "$" in raw or "USD" in raw.upper(): currency = "USD"
    elif "€" in raw or "EUR" in raw.upper(): currency = "EUR"
    elif "грн" in raw.lower() or "UAH" in raw.upper() or "₴" in raw: currency = "UAH"

                                                  
    raw_clean = re.sub(r"[^\d.,]", "", raw.replace("\xa0", "").replace(" ", ""))

                           
                                                       
                                 
    raw_clean = raw_clean.strip(".,")

    if not raw_clean: return None, currency

                                                                  
                                                   
    if raw_clean.count(".") > 1:
        raw_clean = raw_clean.replace(".", "")
    elif raw_clean.count(",") > 1:
        raw_clean = raw_clean.replace(",", "")

                                                    
    raw_clean = raw_clean.replace(",", ".")

    try:
        val = float(raw_clean)
        if val > 0: return val, currency
    except ValueError:
        pass

                                             
    nums = re.findall(r"[\d]+", raw)
    if nums:
                                                                 
        joined = "".join(nums)
        try:
            val = float(joined)
            if val > 0: return val, currency
        except ValueError: pass

    return None, currency
