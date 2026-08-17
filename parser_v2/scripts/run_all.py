
"""Autonomous pipeline: enrich and synchronize sheets safely."""
import sys, os, time, logging, re, copy
from decimal import Decimal, InvalidOperation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras, gspread
from google.oauth2.service_account import Credentials
from parser_v2.services.sheets_lock import SheetsLock
from manual_v1 import active_records, capture_sheet_notes

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("run_all")

DB = dict(host="localhost", port=5432, dbname="real_estate", user="admin")
CREDS = "/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json"
SHEET_ID = "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8"

HEADERS = [
    "ID","Ext ID","Фото","Source","Operation","Property Type","URL",
    "Title","AI Title","Description","AI Description",
    "UAH","USD","EUR","Rooms","Area","Floor","Floors Total",
    "District","City","Street","Residential Complex","Metro",
    "Agent Type","Agent Name","Agent Phone","Commission",
    "Created At","Updated At","Коментарі","Telegraph UA","Telegraph EN",
]
COL_WIDTHS = [55,95,80,60,55,80,200,250,200,300,250,80,70,70,50,60,50,50,120,70,180,150,100,80,130,120,90,130,130,100,200,200]




def step1_db_cleanup():
    log.info("=" * 50)
    log.info("STEP 1: DB CLEANUP")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    sqls = [

        """UPDATE active_listings SET description = NULL
           WHERE description IS NOT NULL AND (
             LENGTH(TRIM(description)) < 10
             OR LOWER(TRIM(description)) IN ('опис','описание','description','-','--','---','.','..','...','test','тест','без опису','немає опису')
             OR description LIKE '%%Команда підтримки%%' OR description LIKE '%%команда підтримки%%'
             OR description LIKE '%%Будні з%%' OR description LIKE '%%будні з%%'
             OR description LIKE '%%Робочий час%%' OR description LIKE '%%Вихідні з%%'
           )""",

        """UPDATE active_listings SET ai_description = NULL
           WHERE ai_description IS NOT NULL AND (
             LENGTH(TRIM(ai_description)) < 20
             OR ai_description LIKE '%%Команда підтримки%%'
             OR ai_description LIKE '%%[Назва%%' OR ai_description LIKE '%%[Адреса%%'
           )""",

        """UPDATE active_listings SET ai_title = NULL
           WHERE ai_title IS NOT NULL AND (
             ai_title LIKE '%%комісі%%' OR ai_title LIKE '%%брокер%%'
             OR ai_title LIKE '%%ріелтор%%' OR ai_title LIKE '%%агент%%'
           )""",

        "UPDATE active_listings SET commission = NULL WHERE LOWER(commission) IN ('false','none','0','no','ні','без','')",
        "UPDATE active_listings SET commission = 'Без комісії' WHERE LOWER(commission) LIKE '%%без комісі%%'",

        "UPDATE active_listings SET agent_type = NULL WHERE agent_type IN ('unknown','','none','None')",

        """UPDATE active_listings SET ai_description = REPLACE(ai_description, 'Продається', 'Здається в оренду')
           WHERE operation='rent' AND ai_description LIKE '%%Продається%%'""",

        "UPDATE active_listings SET price_eur = ROUND(price_uah / 51.52) WHERE price_eur IS NULL AND price_uah IS NOT NULL AND price_uah > 0",
        "UPDATE active_listings SET price_eur = ROUND(price_usd * 45.03 / 51.52) WHERE price_eur IS NULL AND price_usd IS NOT NULL AND price_usd > 0",
        "UPDATE active_listings SET price_usd = ROUND(price_uah / 45.03) WHERE price_usd IS NULL AND price_uah IS NOT NULL AND price_uah > 0",
        "UPDATE active_listings SET price_uah = ROUND(price_usd * 45.03) WHERE price_uah IS NULL AND price_usd IS NOT NULL AND price_usd > 0",
    ]
    for sql in sqls:
        try:
            cur.execute(sql)
        except Exception as e:
            log.warning("SQL: %s", str(e)[:80])
            conn.rollback()
    conn.commit()
    cur.close(); conn.close()
    log.info("✅ DB cleanup done")




KYIV_DISTRICTS = {
    "Голосіївський": ["голосіїв","голосеев"],
    "Дарницький": ["дарниц"],
    "Деснянський": ["деснян"],
    "Дніпровський": ["дніпров","днепров"],
    "Оболонський": ["оболон"],
    "Печерський": ["печер"],
    "Подільський": ["поділ","подол","подільськ"],
    "Святошинський": ["святошин"],
    "Солом'янський": ["солом","соломен"],
    "Шевченківський": ["шевченк"],
}

def _extract_from_text(text, r):
    updates = {}
    tl = text.lower()
    if r.get("rooms") is None:
        m = re.search(r"(\d)\s*[-]?\s*(?:кімнат|комнат|к\.?\s*кв|room)", text, re.I)
        if m: updates["rooms"] = int(m.group(1))
        else:
            for pat, val in [("однокімнат|однокомнат|студі",1),("двокімнат|двухкомнат",2),("трикімнат|трехкомнат",3),("чотирикімнат|четырехкомнат",4)]:
                if re.search(pat, text, re.I): updates["rooms"] = val; break
    if r.get("area") is None:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м²|кв\.?\s*м|m²|м2)", text, re.I)
        if m:
            try:
                v = float(m.group(1).replace(",","."))
                if 5 < v < 1000: updates["area"] = v
            except: pass
    if r.get("floor") is None:
        m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
        if m:
            fl, ft = int(m.group(1)), int(m.group(2))
            if 0 < fl < 80: updates["floor"] = fl
            if 0 < ft < 80 and r.get("floors_total") is None: updates["floors_total"] = ft
        else:
            m = re.search(r"(?:поверх|этаж)\s*[:=]?\s*(\d{1,2})", text, re.I)
            if m: updates["floor"] = int(m.group(1))
    if not r.get("district"):
        for canonical, aliases in KYIV_DISTRICTS.items():
            if any(a in tl for a in aliases): updates["district"] = canonical; break
    if not r.get("street"):
        m = re.search(r"(?:вул(?:иця)?\.?|ул\.?|просп\.?|бульв\.?)\s*([^,\n\d]{3,50})", text, re.I)
        if m: updates["street"] = m.group(1).strip().rstrip(".")
    if not r.get("residential_complex"):
        m = re.search(r'(?:ЖК|жк)\s*[«"\'"\s]*([^»"\'"\n,.;]{2,40})', text)
        if m: updates["residential_complex"] = m.group(1).strip().rstrip('"\'»')
    if not r.get("commission"):
        if "без комісі" in tl or "без комис" in tl: updates["commission"] = "Без комісії"
        else:
            m = re.search(r"комісі[яі]?\s*[:=]?\s*(\d+)\s*%", tl)
            if m: updates["commission"] = f"Комісія {m.group(1)}%"
            elif "комісі" in tl: updates["commission"] = "Комісія є"
    if not r.get("agent_type"):
        for w in ["власник","собственник","від власника"]:
            if w in tl: updates["agent_type"] = "owner"; break
        else:
            for w in ["агентств","агенство"]:
                if w in tl: updates["agent_type"] = "agency"; break
            else:
                for w in ["ріелтор","риелтор","агент","брокер"]:
                    if w in tl: updates["agent_type"] = "agent"; break
    return updates

def step2_enrich():
    log.info("=" * 50)
    log.info("STEP 2: DEEP ENRICHMENT")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur_w = conn.cursor()
    cur.execute("""SELECT id, title, description, rooms, area, floor, floors_total,
        district, street, residential_complex, agent_type, commission
        FROM active_listings WHERE status='active' AND source NOT LIKE 'findly%%'""")
    rows = cur.fetchall()
    log.info("Processing %d rows", len(rows))
    updated = 0
    for idx, r in enumerate(rows, 1):
        text = f"{r.get('title','') or ''} {r.get('description','') or ''}"
        updates = _extract_from_text(text, r)
        if updates:
            sets = ", ".join(f"{k}=%s" for k in updates)
            cur_w.execute(f"UPDATE active_listings SET {sets} WHERE id=%s", list(updates.values()) + [r["id"]])
            updated += 1
        if idx % 10000 == 0:
            conn.commit()
            log.info("  [%d/%d] updated=%d", idx, len(rows), updated)

    cur_w.execute("UPDATE active_listings SET commission='Не вказано' WHERE (commission IS NULL OR commission='') AND status='active' AND source NOT LIKE 'findly%%'")
    cur_w.execute("UPDATE active_listings SET agent_type='Не вказано' WHERE (agent_type IS NULL OR agent_type='') AND status='active' AND source NOT LIKE 'findly%%'")
    cur_w.execute("UPDATE active_listings SET city='Київ' WHERE (city IS NULL OR city='') AND status='active' AND source NOT LIKE 'findly%%'")
    conn.commit()
    cur.close(); cur_w.close(); conn.close()
    log.info("✅ Enrichment done: %d rows updated", updated)




def safe_str(val, max_len=500):
    if val is None: return ""
    s = str(val).strip()
    if s in ("None","none","null","NULL","False","false"): return ""
    s = s[:max_len]
    return "'" + s if s.startswith(("=", "+", "-", "@")) else s

def safe_int(val):
    if val is None: return ""
    try: return str(int(float(val)))
    except: return ""

def display_external_id(row):
    source = str(row.get("source") or "").strip().lower()
    url = str(row.get("url") or "")
    if source == "olx":
        match = re.search(r"\b(ID[A-Za-z0-9]+)\.html", url)
        if match:
            return f"olx_{match.group(1)}"
    if source == "rieltor":
        match = re.search(r"/(\d+)/?(?:[?#].*)?$", url)
        if match:
            return f"rieltor_{match.group(1)}"
    return str(row.get("external_id") or "")

def row30(r):
    pu = r.get("photo_url") or ""
    photo = f'=IMAGE("{pu}")' if pu and pu.startswith("http") else ""
    comm = safe_str(r.get("commission"), 50)
    if comm.lower() in ("false","none","0"): comm = ""
    at = safe_str(r.get("agent_type"), 30)
    if at.lower() in ("unknown","none"): at = ""
    return [
        safe_str(r.get("id"),12), safe_str(display_external_id(r),40),
        photo, safe_str(r.get("source"),20), safe_str(r.get("operation"),10),
        safe_str(r.get("property_type")) or "Квартира", safe_str(r.get("url"),500),
        safe_str(r.get("title"),300), safe_str(r.get("ai_title"),200),
        safe_str(r.get("description"),49000), safe_str(r.get("ai_description"),49000),
        safe_int(r.get("price_uah")), safe_int(r.get("price_usd")), safe_int(r.get("price_eur")),
        safe_str(r.get("rooms"),5), safe_str(r.get("area"),10),
        safe_str(r.get("floor"),5), safe_str(r.get("floors_total"),5),
        safe_str(r.get("district"),50), safe_str(r.get("city")) or "Київ",
        safe_str(r.get("street"),100), safe_str(r.get("residential_complex"),80),
        safe_str(r.get("metro_station"),50),
        at, safe_str(r.get("agent_name"),80),
        safe_str(r.get("agent_phone"),50), comm,
        safe_str(r.get("created_at"),19), safe_str(r.get("updated_at"),19),
        safe_str(r.get("comments"),100),
        "", "",
    ]

def _sheets_update_with_retry(ws, range_name, values, max_retries=5):
    for attempt in range(max_retries):
        try:
            ws.update(range_name=range_name, values=values, value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 60 * (attempt + 1)
                log.warning("  Google API 429 — waiting %ds...", wait)
                time.sleep(wait)
            elif "Connection" in err or "RemoteDisconnected" in err:
                wait = 10 * (attempt + 1)
                log.warning("  Connection error — retry in %ds...", wait)
                time.sleep(wait)
            else:
                log.error("  Sheets error: %s", err[:100])
                time.sleep(5)
    return False

def _sheets_batch_update_with_retry(ws, updates, max_retries=5):
    for attempt in range(max_retries):
        try:
            ws.batch_update(copy.deepcopy(updates), value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 60 * (attempt + 1)
                log.warning("Google API 429 — waiting %ds", wait)
                time.sleep(wait)
            elif "Connection" in err or "RemoteDisconnected" in err:
                wait = 10 * (attempt + 1)
                log.warning("Connection error — retry in %ds", wait)
                time.sleep(wait)
            else:
                log.error("Sheets batch error: %s", err[:100])
                time.sleep(5)
    return False

def _sheets_append_with_retry(ws, values, max_retries=5):
    for attempt in range(max_retries):
        try:
            ws.append_rows(values, value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 60 * (attempt + 1)
                log.warning("Google API 429 — waiting %ds", wait)
                time.sleep(wait)
            elif "Connection" in err or "RemoteDisconnected" in err:
                wait = 10 * (attempt + 1)
                log.warning("Connection error — retry in %ds", wait)
                time.sleep(wait)
            else:
                log.error("Sheets append error: %s", err[:100])
                time.sleep(5)
    return False

def _spreadsheet_batch_with_retry(spreadsheet, requests, max_retries=5):
    for attempt in range(max_retries):
        try:
            spreadsheet.batch_update({"requests": copy.deepcopy(requests)})
            return True
        except Exception as e:
            err = str(e)
            if "429" in err or "500" in err or "503" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 15 * (attempt + 1)
                log.warning("Google API row-delete error — waiting %ds", wait)
                time.sleep(wait)
            elif "Connection" in err or "RemoteDisconnected" in err:
                wait = 10 * (attempt + 1)
                log.warning("Connection error — retry in %ds", wait)
                time.sleep(wait)
            else:
                log.error("Sheets row-delete error: %s", err[:120])
                time.sleep(5)
    return False

def _delete_sheet_rows(ws, positions):
    """Delete original row positions from bottom to top without index drift."""
    ranges = []
    for row in sorted(set(positions), reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    requests = [
        {"deleteDimension": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": start - 1, "endIndex": end,
        }}}
        for start, end in ranges
    ]
    for index in range(0, len(requests), 100):
        if not _spreadsheet_batch_with_retry(ws.spreadsheet, requests[index:index + 100]):
            raise RuntimeError(f"Could not delete stale rows {index + 1}-{min(index + 100, len(requests))}")
    return len(set(positions))

def _clear_sheet_rows(ws, positions):
    """Remove stale Active values without shifting surviving row coordinates."""
    ranges = []
    for row in sorted(set(positions), reverse=True):
        if ranges and row == ranges[-1][0] - 1:
            ranges[-1][0] = row
        else:
            ranges.append([row, row])
    for index in range(0, len(ranges), 25):
        clear_ranges = [f"A{start}:AF{end}" for start, end in ranges[index:index + 25]]
        if not clear_ranges:
            continue
        for attempt in range(4):
            try:
                ws.batch_clear(clear_ranges)
                break
            except Exception as exc:
                if attempt == 3 or not any(code in str(exc) for code in ("429", "500", "503", "timed out", "Timeout", "Connection")):
                    raise
                time.sleep(min(30, 2 ** attempt))
    return len(set(positions))

def _write_new_sheet_rows(ws, start_row, rows):
    for index in range(0, len(rows), 25):
        batch = rows[index:index + 25]
        first = start_row + index
        last = first + len(batch) - 1
        if not _sheets_update_with_retry(ws, f"A{first}:AF{last}", batch):
            raise RuntimeError(f"Could not write new rows {first}-{last} in {ws.title}")
    return len(rows)

def _sheets_read_with_retry(callback, max_retries=5):
    for attempt in range(max_retries):
        try:
            return callback()
        except Exception as e:
            err = str(e)
            if "429" in err or "500" in err or "503" in err or "RESOURCE_EXHAUSTED" in err or "Internal error" in err:
                wait = 15 * (attempt + 1)
                log.warning("Google API read error — waiting %ds", wait)
                time.sleep(wait)
            elif "Connection" in err or "RemoteDisconnected" in err:
                wait = 10 * (attempt + 1)
                log.warning("Connection error — retry in %ds", wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Google Sheets read failed after retries")

def _cell_matches(existing, expected):




    left = str(existing).strip().lstrip("'")
    right = str(expected).strip().lstrip("'")
    if left == right:
        return True
    try:
        return Decimal(left.replace(",", ".")) == Decimal(right.replace(",", "."))
    except InvalidOperation:
        return False

def _row_matches(existing, expected):
    if len(existing) < len(expected):
        return False


    return all(_cell_matches(existing[index], expected[index]) for index in range(len(expected)) if index not in {2, 27, 28, 29, 30, 31})

def _format_due(tab):
    marker = os.path.join("logs", f".sheet_format_{tab}")
    try:
        return time.time() - os.path.getmtime(marker) >= 86400
    except FileNotFoundError:
        return True

def _mark_formatted(tab):
    marker = os.path.join("logs", f".sheet_format_{tab}")
    with open(marker, "a", encoding="utf-8"):
        pass
    os.utime(marker, None)

def step3_sync_sheets():
    log.info("=" * 50)
    log.info("STEP 3: SYNC SHEETS")
    gc = gspread.authorize(Credentials.from_service_account_file(CREDS,
        scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]))
    gc.http_client.timeout = (20, 60)
    sp = gc.open_by_key(SHEET_ID)
    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    for operation, tab in [("rent", "Оренда"), ("buy", "Продаж")]:
        cur.execute("""SELECT * FROM active_listings
            WHERE status='active' AND operation=%s AND source NOT LIKE 'findly%%'
            ORDER BY updated_at DESC""", (operation,))
        rows = [dict(r) for r in cur.fetchall()]
        rows.extend(active_records(conn, 'apartments', operation))
        log.info("%s: %d rows", tab, len(rows))

        try:
            ws = sp.worksheet(tab)
        except gspread.WorksheetNotFound:
            ws = sp.add_worksheet(title=tab, rows=max(len(rows) + 5, 1000), cols=32)
        if ws.col_count > len(HEADERS):
            _sheets_read_with_retry(lambda: ws.resize(cols=len(HEADERS)))
        header = _sheets_read_with_retry(lambda: ws.row_values(1))
        if header and header != HEADERS:
            raise RuntimeError(f"Unexpected header in {tab}; refusing to overwrite existing data")
        if not header and not _sheets_update_with_retry(ws, "A1:AF1", [HEADERS]):
            raise RuntimeError(f"Could not create header in {tab}")
        existing = _sheets_read_with_retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
        capture_sheet_notes(conn, "apartments", existing, 0, 29)
        rows_by_id = {}
        duplicate_ids = 0
        duplicate_positions = []
        orphan_positions = []
        for row_number, values in enumerate(existing[1:], start=2):
            if not values or not str(values[0]).strip():
                if any(str(value).strip() for value in values):
                    orphan_positions.append(row_number)
                continue
            identifier = str(values[0]).strip()
            if identifier in rows_by_id:
                duplicate_ids += 1
                duplicate_positions.append(row_number)
                continue
            rows_by_id[identifier] = (row_number, values)
        updates = []
        appends = []
        expected_ids = set()
        for record in rows:
            values = row30(record)
            expected_ids.add(values[0])
            existing_row = rows_by_id.get(values[0])
            if existing_row is None:
                appends.append(values)
            elif not _row_matches(existing_row[1], values):


                updates.extend([
                    {"range": f"A{existing_row[0]}:AC{existing_row[0]}", "values": [values[:29]]},
                    {"range": f"AE{existing_row[0]}:AF{existing_row[0]}", "values": [values[30:]]},
                ])
        for index in range(0, len(updates), 50):
            if not _sheets_batch_update_with_retry(ws, updates[index:index + 50]):
                raise RuntimeError(f"Could not update {tab} rows {index + 1}-{min(index + 50, len(updates))}")
        stale_positions = [position for identifier, (position, _) in rows_by_id.items() if identifier not in expected_ids]


        removed = _delete_sheet_rows(ws, stale_positions + duplicate_positions + orphan_positions)
        current_after_delete = _sheets_read_with_retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
        required_rows = len(current_after_delete) + len(appends) + 10
        if ws.row_count < required_rows:
            _sheets_read_with_retry(lambda: ws.resize(rows=required_rows))
        appended = _write_new_sheet_rows(ws, len(current_after_delete) + 1, appends)
        log.info("%s: updated_ranges=%d appended=%d removed=%d duplicate_ids=%d orphan_rows=%d", tab, len(updates), appended, removed, duplicate_ids, len(orphan_positions))


        if not _format_due(tab):
            log.info("  Formatting for %s is current", tab)
            log.info("  ✅ %s: %d active rows synced", tab, len(rows))
            time.sleep(5)
            continue
        sid = ws.id
        requests = [
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(rows)+2,
                "startColumnIndex": 0, "endColumnIndex": 32},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 28}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 1, "endIndex": len(rows)+2},
                "properties": {"pixelSize": 42}, "fields": "pixelSize"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 32},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.92}}},
                "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
        ]
        for i, w in enumerate(COL_WIDTHS):
            requests.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                "startIndex": i, "endIndex": i+1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}})
        try:
            sp.batch_update({"requests": requests})
            _mark_formatted(tab)
        except Exception as e:
            log.warning("Formatting error: %s", str(e)[:80])
        log.info("  ✅ %s: %d active rows synced", tab, len(rows))
        time.sleep(5)

    cur.close(); conn.close()
    log.info("✅ Sheets rebuild complete")




def step4_report():
    log.info("=" * 50)
    log.info("STEP 4: COVERAGE REPORT")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute("""SELECT source, operation, count(*) as total,
        round(100.0*count(*) FILTER (WHERE rooms IS NOT NULL)/count(*)) as rooms,
        round(100.0*count(*) FILTER (WHERE area IS NOT NULL)/count(*)) as area,
        round(100.0*count(*) FILTER (WHERE floor IS NOT NULL)/count(*)) as floor,
        round(100.0*count(*) FILTER (WHERE district!='' AND district IS NOT NULL)/count(*)) as dist,
        round(100.0*count(*) FILTER (WHERE street!='' AND street IS NOT NULL)/count(*)) as street,
        round(100.0*count(*) FILTER (WHERE residential_complex!='' AND residential_complex IS NOT NULL)/count(*)) as rc,
        round(100.0*count(*) FILTER (WHERE agent_type IS NOT NULL AND agent_type!='')/count(*)) as agent,
        round(100.0*count(*) FILTER (WHERE commission IS NOT NULL AND commission!='')/count(*)) as comm,
        round(100.0*count(*) FILTER (WHERE array_length(photos,1)>0)/count(*)) as photos,
        round(100.0*count(*) FILTER (WHERE description IS NOT NULL AND LENGTH(description)>30)/count(*)) as descp
    FROM active_listings WHERE status='active' AND source NOT LIKE 'findly%%'
    GROUP BY 1,2 ORDER BY 1,2""")
    log.info(f"  {'src':10} {'op':6} {'tot':>6} {'room':>5} {'area':>5} {'flr':>5} {'dist':>5} {'str':>5} {'RC':>5} {'agnt':>5} {'comm':>5} {'phot':>5} {'desc':>5}")
    log.info("  " + "-" * 100)
    for r in cur.fetchall():
        log.info(f"  {r[0]:10} {r[1]:6} {r[2]:>6} {r[3]:>5} {r[4]:>5} {r[5]:>5} {r[6]:>5} {r[7]:>5} {r[8]:>5} {r[9]:>5} {r[10]:>5} {r[11]:>5} {r[12]:>5}")
    cur.close(); conn.close()




if __name__ == "__main__":
    log.info("🚀 AUTONOMOUS PIPELINE STARTED")
    t0 = time.time()
    step1_db_cleanup()
    step2_enrich()
    try:
        with SheetsLock("run_all", wait_seconds=900):
            step3_sync_sheets()
    except RuntimeError as exc:




        if str(exc).startswith("Sheets writer already running:"):
            log.warning("Sheets sync deferred: %s", exc)
        else:
            raise
    step4_report()
    elapsed = time.time() - t0
    log.info("🏁 ALL COMPLETE in %.0f minutes", elapsed / 60)
