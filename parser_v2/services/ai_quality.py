"""AI content quality validation."""
from __future__ import annotations
import re

BAD_TITLES = {"квартира","продаж","оренда","житло","нерухомість","apartment","sale","rent","flat","test","тест"}
SPAM_WORDS = {"комісія","комиссия","broker","брокер","call now","зателефонуйте","звоните","срочно","терміново"}

def score_title(title: str | None, rooms=None, area=None, district=None) -> tuple[int, str]:
    if not title or len(title.strip()) < 6: return 0, "too_short"
    t = title.strip().lower()
    if t in BAD_TITLES: return 0, "generic"
    words = t.split()
    if len(words) < 2: return 20, "single_word"
    score = 50
    if rooms and str(rooms) in title: score += 10
    if area and str(area) in title: score += 10
    if district and district.lower() in t: score += 15
    if "жк" in t or "ЖК" in title: score += 10
    if len(words) >= 4: score += 5
    return min(score, 100), "ok"

def score_description(desc: str | None) -> tuple[int, str]:
    if not desc or len(desc.strip()) < 40: return 0, "too_short"
    d = desc.strip()
    if any(w in d.lower() for w in SPAM_WORDS): return 20, "spam"
    if re.search(r'[{}\[\]<>]', d): return 10, "technical_junk"
    sentences = [s.strip() for s in re.split(r'[.!?]', d) if len(s.strip()) > 5]
    score = 40
    if len(sentences) >= 2: score += 20
    if len(sentences) >= 3: score += 15
    if len(d) > 100: score += 10
    if len(d) > 200: score += 10
    return min(score, 100), "ok"

def passes_quality(title: str|None, desc: str|None, rooms=None, area=None, district=None,
                   min_title: int = 30, min_desc: int = 30) -> tuple[bool, dict]:
    ts, tr = score_title(title, rooms, area, district)
    ds, dr = score_description(desc)
    return (ts >= min_title and ds >= min_desc), {"title_score": ts, "title_reason": tr, "desc_score": ds, "desc_reason": dr}
