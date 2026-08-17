                      
"""Reparse ONLY listings missing rooms/area/floor/district from live pages."""
import sys, os, re, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.logging_setup import get_logger
from parser_v2.services.process_lock import acquire_process_lock

log = get_logger("reparse_fields")
try:
    PROCESS_LOCK = acquire_process_lock("reparse_fields")
except RuntimeError:
    log.info("reparse_fields already running")
    sys.exit(0)
DB = dict(host="localhost", port=5432, dbname="real_estate", user="admin")

KYIV_DISTRICTS = {
    "Голосіївський": ["голосіїв","голосеев"],
    "Дарницький": ["дарниц"],
    "Деснянський": ["деснян"],
    "Дніпровський": ["дніпров","днепров"],
    "Оболонський": ["оболон"],
    "Печерський": ["печер"],
    "Подільський": ["поділ","подол"],
    "Святошинський": ["святошин"],
    "Солом'янський": ["солом","соломен"],
    "Шевченківський": ["шевченк"],
}

def extract_from_html(html: str, source: str) -> dict:
    """Extract rooms/area/floor/district from raw HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    d = {}
    text = soup.get_text()
    tl = text.lower()

    if source == "rieltor":
                                           
        for row in soup.select("div.offer-view-details-row"):
            t = row.get_text().strip(); rtl = t.lower()
            if "кімнат" in rtl:
                m = re.search(r"(\d+)", t)
                if m: d["rooms"] = int(m.group(1))
            elif "м²" in rtl or "м2" in rtl:
                m = re.search(r"([\d.,]+)\s*/", t) or re.search(r"([\d.,]+)\s*м", t)
                if m:
                    try: d["area"] = float(m.group(1).replace(",","."))
                    except: pass
            elif "поверх" in rtl:
                m = re.search(r"(\d+)\s*(?:з|із)\s*(\d+)", t)
                if m: d["floor"] = int(m.group(1)); d["floors_total"] = int(m.group(2))

                                
        for b in soup.find_all("b"):
            bt = b.get_text().strip().lower()
            nxt = b.next_sibling
            val = ""
            while nxt:
                if hasattr(nxt, 'get_text'): val = nxt.get_text().strip()
                elif isinstance(nxt, str): val = nxt.strip()
                if val: break
                nxt = nxt.next_sibling
            if not val: continue
            if "кількість кімнат" in bt and "rooms" not in d:
                m = re.search(r"(\d+)", val)
                if m: d["rooms"] = int(m.group(1))
            elif "загальна площа" in bt and "area" not in d:
                m = re.search(r"([\d.,]+)", val)
                if m:
                    try: d["area"] = float(m.group(1).replace(",","."))
                    except: pass
            elif bt.startswith("поверх") and "поверховість" not in bt and "floor" not in d:
                m = re.search(r"(\d+)", val)
                if m: d["floor"] = int(m.group(1))
            elif "поверховість" in bt and "floors_total" not in d:
                m = re.search(r"(\d+)", val)
                if m: d["floors_total"] = int(m.group(1))

                                         
        region = soup.select_one("div.offer-view-region")
        if region:
            parts = [p.strip() for p in region.get_text().split(",")]
            if len(parts) > 1:
                dist = parts[1].replace("р-н","").replace("район","").strip()
                if dist: d["district"] = dist

                                 
        og = soup.find("meta", property="og:description")
        if og:
            og_text = og.get("content","")
            if "rooms" not in d:
                m = re.search(r"(\d+)\s*кімнат", og_text)
                if m: d["rooms"] = int(m.group(1))
            if "floor" not in d:
                m = re.search(r"(\d+)\s*поверх\s*(\d+)", og_text)
                if m: d["floor"] = int(m.group(1)); d["floors_total"] = int(m.group(2))
            if "area" not in d:
                m = re.search(r"([\d.,]+)\s*/\s*[\d.,]+\s*/\s*[\d.,]+\s*м", og_text)
                if m:
                    try: d["area"] = float(m.group(1).replace(",","."))
                    except: pass

    elif source == "olx":
                                                       
        import json
        for s in soup.select('script[type="application/ld+json"]'):
            try:
                ld = json.loads(s.string or "")
                if isinstance(ld, dict):
                    if ld.get("numberOfRooms"): d["rooms"] = int(ld["numberOfRooms"])
                    if isinstance(ld.get("floorSize"), dict):
                        v = ld["floorSize"].get("value")
                        if v:
                            try: d["area"] = float(str(v).replace(",","."))
                            except: pass
                    addr = ld.get("address", {})
                    if isinstance(addr, dict) and addr.get("addressLocality"):
                        d.setdefault("district", addr["addressLocality"])
            except: pass

                                                               
        meta = soup.find("meta", {"name": "description"})
        if meta:
            mc = meta.get("content", "")
            if "rooms" not in d:
                m = re.search(r"(?:Кількість кімнат|Комнат|Rooms?)[:=\s]*(\d+)", mc, re.I)
                if m: d["rooms"] = int(m.group(1))
            if "area" not in d:
                m = re.search(r"(?:Площ[аі]|Area)[:=\s]*([\d.,]+)", mc, re.I)
                if m:
                    try: d["area"] = float(m.group(1).replace(",","."))
                    except: pass
            if "floor" not in d:
                m = re.search(r"(?:Поверх|Этаж|Floor)[:=\s]*(\d+)", mc, re.I)
                if m: d["floor"] = int(m.group(1))

                                                  
    if "district" not in d:
        for canonical, aliases in KYIV_DISTRICTS.items():
            if any(a in tl for a in aliases):
                d["district"] = canonical; break

                                                          
    if "rooms" not in d:
        m = re.search(r"(\d)\s*[-]?\s*(?:кімнат|комнат|room)", text, re.I)
        if m: d["rooms"] = int(m.group(1))
    if "area" not in d:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м²|кв\.?\s*м|m²|м2)", text, re.I)
        if m:
            try:
                v = float(m.group(1).replace(",","."))
                if 5 < v < 1000: d["area"] = v
            except: pass
    if "floor" not in d:
        m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
        if m:
            fl, ft = int(m.group(1)), int(m.group(2))
            if 0 < fl < 80: d["floor"] = fl
            if 0 < ft < 80: d["floors_total"] = ft

                 
    if source == "rieltor":
        desc_el = soup.select_one("div.offer-view-section-text")
        if desc_el:
            desc = desc_el.get_text().strip()
            if len(desc) > 30:
                                    
                bad = ["команда підтримки","будні з","вихідні з","робочий час"]
                if not any(b in desc.lower() for b in bad):
                    # Preserve the full source text when this maintenance tool
                    # refreshes a listing; 49k is below the Sheets cell limit.
                    d["description"] = desc[:49000]
    elif source == "olx":
                                          
        meta_d = soup.find("meta", {"name": "description"})
        if meta_d:
            desc = meta_d.get("content", "").strip()
            if len(desc) > 30:
                bad = ["команда підтримки","будні з","вихідні з"]
                if not any(b in desc.lower() for b in bad):
                    d["description"] = desc[:49000]

    return d

def reparse_source(source: str):
    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur_w = conn.cursor()

    cur.execute("""SELECT id, url, external_id, source, operation, description
        FROM active_listings
        WHERE status='active' AND source=%s
          AND url IS NOT NULL AND url != ''
          AND (rooms IS NULL OR area IS NULL OR floor IS NULL
               OR district IS NULL OR district = ''
               OR description IS NULL OR LENGTH(TRIM(COALESCE(description,''))) < 30)
        ORDER BY updated_at DESC""", (source,))
    rows = cur.fetchall()
    log.info("=== %s: %d listings missing fields ===", source.upper(), len(rows))

    if source == "olx":
        http = OlxHttpClient(timeout=30); http._min_delay = 0.5
    else:
        http = RieltorHttpClient(timeout=30); http._min_delay = 4.0

    stats = {"updated": 0, "dead": 0, "failed": 0, "fields": 0}
    t0 = time.time()

    for idx, r in enumerate(rows, 1):
        try:
            status, html = http.get(r["url"])
            if status in (404, 410):
                stats["dead"] += 1
                continue
            if status != 200:
                stats["failed"] += 1; continue

            extracted = extract_from_html(html, source)
                                     
            updates = {}
            if r.get("rooms") is None and "rooms" in extracted:
                updates["rooms"] = extracted["rooms"]
            if r.get("area") is None and "area" in extracted:
                updates["area"] = extracted["area"]
            if r.get("floor") is None and "floor" in extracted:
                updates["floor"] = extracted["floor"]
            if r.get("floors_total") is None and "floors_total" in extracted:
                updates["floors_total"] = extracted["floors_total"]
            if (not r.get("district") or r["district"] == "") and "district" in extracted:
                updates["district"] = extracted["district"]
            if (not r.get("description") or len(str(r.get("description",""))) < 30) and "description" in extracted:
                updates["description"] = extracted["description"]

            if updates:
                sets = ", ".join(f"{k}=%s" for k in updates)
                cur_w.execute(f"UPDATE active_listings SET {sets}, updated_at=NOW() WHERE id=%s",
                             list(updates.values()) + [r["id"]])
                conn.commit()
                stats["updated"] += 1
                stats["fields"] += len(updates)

        except Exception as e:
            stats["failed"] += 1

        if idx % 50 == 0 or idx == len(rows):
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(rows) - idx) / rate / 60 if rate > 0 else 0
            log.info("[%d/%d] updated=%d dead=%d failed=%d fields=%d (%.1f/s ETA %.0fm)",
                     idx, len(rows), stats["updated"], stats["dead"],
                     stats["failed"], stats["fields"], rate, eta)

    http.close()
    cur.close(); cur_w.close(); conn.close()
    log.info("=== %s DONE: %s ===", source.upper(), stats)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["olx","rieltor","all"], default="all")
    args = ap.parse_args()
    for s in (["olx","rieltor"] if args.source == "all" else [args.source]):
        reparse_source(s)

                  
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute("""SELECT source, operation,
        count(*) FILTER (WHERE rooms IS NULL) as no_rooms,
        count(*) FILTER (WHERE area IS NULL) as no_area,
        count(*) FILTER (WHERE floor IS NULL) as no_floor,
        count(*) FILTER (WHERE district IS NULL OR district='') as no_dist,
        count(*) FILTER (WHERE description IS NULL OR LENGTH(TRIM(COALESCE(description,''))) < 30) as no_desc,
        count(*) as total
    FROM active_listings WHERE status='active' AND source NOT LIKE 'findly%%'
    GROUP BY 1,2 ORDER BY 1,2""")
    log.info("\nREMAINING GAPS:")
    for r in cur.fetchall():
        log.info("  %s %s: rooms=%d area=%d floor=%d dist=%d desc=%d (of %d)", r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7])
    cur.close(); conn.close()
                                                                        
