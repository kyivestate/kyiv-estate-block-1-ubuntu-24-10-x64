"""Pipeline V2 — full orchestrator."""
from __future__ import annotations
import argparse, time, re, os, subprocess, sys
from datetime import datetime, timedelta, timezone
import psycopg2
import psycopg2.extras
from parser_v2.config import cfg
from parser_v2.models.listing import NormalizedListing
from parser_v2.parsers.olx_v2 import OlxParser
from parser_v2.parsers.rieltor_v2 import RieltorParser
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from parser_v2.services.normalizers import normalize_listing
from parser_v2.services.photo_uploader import photo_uploader
from parser_v2.services.persistence import get_conn, save_raw_listing, save_normalized_listing, merge_v2_into_active
from parser_v2.services.sheets_lock import SheetsLock
from parser_v2.services.process_lock import acquire_process_lock
from parser_v2.services.logging_setup import get_logger
log = get_logger("pipeline")

def run_parser(source: str, operation: str, dry_run: bool = False, property_types: set[str] | None = None) -> list[NormalizedListing]:
    log.info("=== %s/%s dry_run=%s ===", source, operation, dry_run)
    conn = get_conn()
    if source == "olx":
        http = OlxHttpClient(cfg.parser.request_timeout)
        parser = OlxParser(http, operation, cfg.parser.olx_max_pages, property_types)
    else:
        http = RieltorHttpClient(cfg.parser.request_timeout)
        parser = RieltorParser(http, operation, cfg.parser.rieltor_max_pages, property_types)
    urls = parser.collect_listing_urls()
    total = len(urls)
    log.info("Found %d URLs", total)
    normalized = []; stats = {"parsed": 0, "failed": 0, "filtered": 0, "price_skip": 0}
    t0 = time.time()
    for idx, entry in enumerate(urls, 1):
        try:
            raw, sd = parser.fetch_and_parse(entry["url"], entry["external_id"])
            if raw.parse_status != "parsed":
                if raw.parse_status == "failed": stats["failed"] += 1
                else: stats["filtered"] += 1
                if not dry_run:
                    try: save_raw_listing(conn, raw); conn.commit()
                    except: conn.rollback()
            else:
                nl = normalize_listing(raw, sd)


                if property_types is not None and nl.property_type not in property_types:
                    stats["filtered"] += 1
                    if not dry_run:
                        try:
                            save_raw_listing(conn, raw); conn.commit()
                        except Exception:
                            conn.rollback()
                elif not nl.passes_price_filter(cfg.parser.rent_min_uah, cfg.parser.sale_min_usd):
                    stats["price_skip"] += 1
                else:
                    if cfg.parser.upload_photos and nl.photos:
                        cdns = photo_uploader.upload_batch(nl.photos[:cfg.parser.max_photos_per_listing], f"{nl.source}_{nl.external_id}")
                        if cdns: nl.cdn_photos = cdns; nl.cdn_photo_url = cdns[0]; nl.sheet_image_formula = f'=IMAGE("{cdns[0]}")'
                    if not dry_run:
                        try:
                            rid = save_raw_listing(conn, raw); nl.raw_listing_id = rid
                            save_normalized_listing(conn, nl); conn.commit()
                        except Exception as e: conn.rollback(); log.error("DB: %s", e)
                    normalized.append(nl); stats["parsed"] += 1
        except Exception as e:
            stats["failed"] += 1; log.error("[%d/%d] %s: %s", idx, total, entry.get("url","?")[:60], e)
        if idx % 25 == 0 or idx == total:
            elapsed = time.time() - t0; rate = idx / elapsed if elapsed > 0 else 0
            eta = (total - idx) / rate if rate > 0 else 0
            log.info("[%d/%d] parsed=%d failed=%d skip=%d (%.1f/s ETA %.0fs)",
                     idx, total, stats["parsed"], stats["failed"], stats["price_skip"], rate, eta)
    http.close(); conn.close()
    log.info("=== %s/%s DONE %.0fs: %s ===", source, operation, time.time() - t0, stats)
    return normalized

def run_merge(since: datetime | None = None, max_attempts: int = 5) -> int:
    for attempt in range(max_attempts):
        conn = get_conn()
        try:
            return merge_v2_into_active(conn, since=since)
        except psycopg2.errors.DeadlockDetected:
            conn.rollback()
            if attempt + 1 == max_attempts:
                raise
            delay = 2 ** attempt
            log.warning("Merge deadlock; retrying in %ss (%d/%d)", delay, attempt + 1, max_attempts)
            time.sleep(delay)
        finally:
            conn.close()
    raise RuntimeError("Merge retry loop ended unexpectedly")

def _check_parallel_writers():
    try:
        out = subprocess.check_output("ps aux", shell=True, text=True)
        dangerous = []
        for name in ["continuoussync", "syncnewtables", "fixactivesheets", "pipelinev5"]:
            if name in out: dangerous.append(name)
        if dangerous:
            log.error("PARALLEL WRITERS DETECTED: %s — aborting sheets!", dangerous)
            return False
    except: pass
    return True

SHEET_HEADERS_30 = [
    "Фото", "Source", "Operation", "Property Type", "URL",
    "Title", "AI Title", "Description", "AI Description",
    "UAH", "USD", "EUR", "Rooms", "Area", "Floor", "Floors Total",
    "District", "City", "Street", "Residential Complex", "Metro",
    "Agent Type", "Agent Name", "Agent Phone", "Commission",
    "Created At", "Updated At", "Коментарі", "Telegraph UA", "Telegraph EN",
]

def _db_row_to_30_cols(r: dict) -> list[str]:
    pu = r.get("photo_url") or ""
    photo = f'=IMAGE("{pu}")' if pu and pu.startswith("http") else ""
    return [
        photo,
        str(r.get("source", "") or ""),
        str(r.get("operation", "") or ""),
        str(r.get("property_type", "") or "Квартира"),
        str(r.get("url", "") or ""),
        str(r.get("title", "") or "")[:300],
        str(r.get("ai_title", "") or ""),


        str(r.get("description", "") or "")[:49000],
        str(r.get("ai_description", "") or "")[:49000],
        str(r.get("price_uah", "") or ""),
        str(r.get("price_usd", "") or ""),
        str(r.get("price_eur", "") or ""),
        str(r.get("rooms", "") or ""),
        str(r.get("area", "") or ""),
        str(r.get("floor", "") or ""),
        str(r.get("floors_total", "") or ""),
        str(r.get("district", "") or ""),
        str(r.get("city", "") or "Київ"),
        str(r.get("street", "") or ""),
        str(r.get("residential_complex", "") or ""),
        str(r.get("metro_station", "") or ""),
        str(r.get("agent_type", "") or ""),
        str(r.get("agent_name", "") or ""),
        str(r.get("agent_phone", "") or ""),
        str(r.get("commission", "") or ""),
        str(r.get("created_at", "") or "")[:19],
        str(r.get("updated_at", "") or "")[:19],
        str(r.get("comments", "") or ""),
        "",
        "",
    ]

def run_sheets_restore():
    """Retired: scheduled parsing writes PostgreSQL only."""
    log.warning("Sheets restore is retired; use the canonical run_all.py writer.")
    return
    if not _check_parallel_writers(): return
    import gspread
    from google.oauth2.service_account import Credentials

    ACTIVE_ID = cfg.sheets.active_sheet_id
    log.info("Sheets restore -> %s", ACTIVE_ID[:20])

    with SheetsLock("pipeline_v2_restore"):
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(cfg.sheets.credentials_file, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sp = gc.open_by_key(ACTIVE_ID)
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for operation, tab_name in [("rent", cfg.sheets.rent_tab), ("buy", cfg.sheets.sale_tab)]:
                    cur.execute("""SELECT * FROM active_listings
                        WHERE status='active' AND operation=%s
                          AND source NOT LIKE 'findly%%'
                        ORDER BY updated_at DESC""", (operation,))
                    rows = [dict(r) for r in cur.fetchall()]
                    log.info("Tab %s: %d rows from DB", tab_name, len(rows))
                    if not rows:
                        log.warning("No rows for %s!", tab_name); continue

                    try: ws = sp.worksheet(tab_name)
                    except gspread.WorksheetNotFound:
                        ws = sp.add_worksheet(title=tab_name, rows=len(rows)+10, cols=30)


                    existing = ws.get_all_values()
                    url_to_row: dict[str, int] = {}
                    for i, row in enumerate(existing[1:], start=2):
                        if len(row) >= 5 and row[4]:
                            url_to_row[row[4]] = i


                    if not existing or existing[0] != SHEET_HEADERS_30:
                        ws.update("A1:AD1", [SHEET_HEADERS_30], value_input_option="RAW")
                        log.info("Header set for %s", tab_name)
                        time.sleep(1)

                    updates = []
                    appends = []
                    for r in rows:
                        row_data = _db_row_to_30_cols(r)
                        url = r.get("url", "")
                        if url and url in url_to_row:
                            row_num = url_to_row[url]
                            updates.append({"range": f"A{row_num}:AD{row_num}", "values": [row_data]})
                        else:
                            appends.append(row_data)


                    if updates:
                        for i in range(0, len(updates), 200):
                            chunk = updates[i:i+200]
                            ws.batch_update(chunk, value_input_option="USER_ENTERED")
                            log.info("Tab %s: updated rows %d-%d", tab_name, i, i+len(chunk))
                            time.sleep(2)


                    if appends:
                        for i in range(0, len(appends), 500):
                            chunk = appends[i:i+500]

                            log.info("Tab %s: appended %d rows", tab_name, len(chunk))
                            time.sleep(2)

                    log.info("Tab %s DONE: %d updated, %d appended", tab_name, len(updates), len(appends))
                    time.sleep(3)
        finally:
            conn.close()
    log.info("Sheets restore complete!")

def main():
    try:
        process_lock = acquire_process_lock("pipeline_v2")
    except RuntimeError:
        log.warning("pipeline_v2 already running")
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["olx","rieltor","all"], default="all")
    ap.add_argument("--operation", choices=["rent","buy","all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--sync-sheets", action="store_true")
    ap.add_argument("--restore-sheets", action="store_true")
    ap.add_argument("--check-dead", action="store_true")
    ap.add_argument("--no-rebuild-sheets", action="store_true")
    ap.add_argument("--no-dead-check", action="store_true")
    ap.add_argument("--full-merge", action="store_true")
    ap.add_argument("--merge-since-minutes", type=int, default=120)
    ap.add_argument("--property-scope", choices=["apartments", "houses", "all"], default="apartments",
                    help="Production scope. The legacy all scope is retained only for controlled recovery.")
    args = ap.parse_args()
    run_started_at = datetime.now(timezone.utc)
    dry = args.dry_run or cfg.parser.dry_run
    if args.merge_only:
        since = None if args.full_merge else run_started_at - timedelta(minutes=max(args.merge_since_minutes, 1))
        log.info("Merge: %d rows", run_merge(since=since))
        return
    if args.restore_sheets or args.sync_sheets: run_sheets_restore(); return
    if args.check_dead:
        result = subprocess.run([sys.executable, "parser_v2/scripts/check_listing_statuses.py"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if result.returncode:
            raise RuntimeError(f"status verification failed: {result.returncode}")
        return
    sources = ["olx","rieltor"] if args.source == "all" else [args.source]
    ops = ["rent","buy"] if args.operation == "all" else [args.operation]
    total = []
    property_types = {"Квартира"} if args.property_scope == "apartments" else ({"Будинок"} if args.property_scope == "houses" else None)
    for s in sources:
        for o in ops: total.extend(run_parser(s, o, dry, property_types))
    log.info("Total: %d listings", len(total))
    if not dry:
        log.info("Merge: %d rows", run_merge(since=run_started_at))
        if not args.no_rebuild_sheets:
            result = subprocess.run([sys.executable, "parser_v2/scripts/run_all.py"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if result.returncode:
                raise RuntimeError(f"canonical Sheets rebuild failed: {result.returncode}")

    log.info("Pipeline V2 complete.")

if __name__ == "__main__": main()
