"""Safe Google Sheets sync — NO clear(), NO destructive rewrites.
WARNING: НЕ запускати одночасно з continuoussync/syncnewtablestosheets/fixactivesheets!"""
from __future__ import annotations
import time
import gspread
from google.oauth2.service_account import Credentials
from parser_v2.config import cfg
from parser_v2.services.logging_setup import get_logger
log = get_logger("sheets_sync")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
HEADERS = ["Фото","Назва","Ціна UAH","Ціна USD","Ціна EUR","Кімнати","Площа","Поверх","Поверхів",
    "Район","Вулиця","ЖК","Тип","Контакт","Телефон","Джерело","URL","ID","Оновлено"]

def _get_client() -> gspread.Client:
    return gspread.authorize(Credentials.from_service_account_file(cfg.sheets.credentials_file, scopes=SCOPES))

def _row(r: dict) -> list[str]:
    pu = r.get("cdn_photo_url") or r.get("photo_url") or ""
    formula = f'=IMAGE("{pu}")' if pu else ""
    return [formula, str(r.get("title",""))[:200], str(r.get("price_uah","") or ""),
        str(r.get("price_usd","") or ""), str(r.get("price_eur","") or ""),
        str(r.get("rooms","") or ""), str(r.get("area","") or ""),
        str(r.get("floor","") or ""), str(r.get("floors_total","") or ""),
        str(r.get("district","") or ""), str(r.get("street","") or ""),
        str(r.get("residential_complex","") or ""), str(r.get("agent_type","") or ""),
        str(r.get("agent_name","") or ""), str(r.get("agent_phone","") or ""),
        str(r.get("source","") or ""), str(r.get("url","") or ""),
        str(r.get("external_id","") or ""), str(r.get("updated_at","") or "")[:19]]

def safe_sync_to_sheet(listings: list[dict], sheet_id: str, tab_name: str) -> dict[str, int]:
    raise RuntimeError("Retired 19-column append writer. Use scripts/run_all.py only.")
    log.info("Safe sync: %d listings -> %s/%s", len(listings), sheet_id[:12], tab_name)
    client = _get_client()
    sp = client.open_by_key(sheet_id)
    try: ws = sp.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(title=tab_name, rows=1000, cols=len(HEADERS))
    existing_h = ws.row_values(1) if ws.row_count > 0 else []
    if existing_h != HEADERS:
        ws.update("A1", [HEADERS], value_input_option="RAW"); time.sleep(1)
    all_vals = ws.get_all_values()
    emap: dict[str, int] = {}
    for i, row in enumerate(all_vals[1:], start=2):
        if len(row) >= 18 and row[17]: emap[row[17]] = i
    updates, appends = [], []
    stats = {"updated": 0, "appended": 0, "skipped": 0}
    for listing in listings:
        eid = str(listing.get("external_id", ""))
        if not eid: stats["skipped"] += 1; continue
        rd = _row(listing)
        if eid in emap:
            updates.append({"range": f"A{emap[eid]}:S{emap[eid]}", "values": [rd]}); stats["updated"] += 1
        else:
            appends.append(rd); stats["appended"] += 1
    if updates:
        for i in range(0, len(updates), 50):
            ws.batch_update(updates[i:i+50], value_input_option="USER_ENTERED"); time.sleep(1)
    if appends:
        for i in range(0, len(appends), 100):
            ws.append_rows(appends[i:i+100], value_input_option="USER_ENTERED"); time.sleep(1)
    log.info("Sync %s done: %s", tab_name, stats); return stats
