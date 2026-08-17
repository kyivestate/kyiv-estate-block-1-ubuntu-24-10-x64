#!/usr/bin/env python3
"""Import an audited OLX phone export into the three listing contours.

Only exact OLX external-id matches are eligible.  Database writes touch only
``agent_phone`` or ``phones``; Google Sheets writes touch only the existing
phone cells of existing listing rows.  The default mode is read-only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
import phonenumbers
import psycopg2
import psycopg2.extras
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser_v2.services.sheets_lock import SheetsLock


DB = dict(host="localhost", port=5432, dbname="real_estate", user="admin")
CREDS = Path("/Users/admin/Projects/real-estate-platform/olx-parser/ads-collector/real-estate-platform-484610-a5a172df3957.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
BOOKS = {
    "apartments": {"id": "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8", "phone_header": "Agent Phone"},
    "houses": {"id": "1BeIvPPeem-CWYgl2pS1pf1_CxMllcxXCaIstB5IonFY", "phone_header": "Agent Phone"},
    "commercial": {"id": "15eFtcBjMYRAHLgDFP0u6Bo57ORVy8RWZ954Hp6bDDtw", "phone_header": "Телефони"},
}
TABLES = {
    "apartments": ("active_listings", "agent_phone"),
    "houses": ("houses_listings", "agent_phone"),
    "commercial": ("commercial_listings", "phones"),
}
TABS = {"rent": "Оренда", "buy": "Продаж"}


def phone_values(raw: str | None) -> list[str]:
    """Return unique valid Ukrainian phones in E.164 format."""
    if not raw:
        return []
    result: list[str] = []
    for match in phonenumbers.PhoneNumberMatcher(str(raw), "UA"):
        number = match.number
        if phonenumbers.is_possible_number(number) and phonenumbers.is_valid_number(number):
            value = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            if value not in result:
                result.append(value)
    if result:
        return result
    for token in re.split(r"[,;/|\n]+", str(raw)):
        digits = re.sub(r"\D", "", token)
        if len(digits) == 10 and digits.startswith("0"):
            digits = "38" + digits
        if len(digits) == 12 and digits.startswith("380"):
            value = "+" + digits
            if value not in result:
                result.append(value)
    return result


def external_id(row: dict[str, Any]) -> str | None:
    token = str(row.get("external_token") or "").strip()
    if not token:
        match = re.search(r"-ID([A-Za-z0-9]+)\.html", str(row.get("url") or ""), re.I)
        token = match.group(1) if match else ""
    return f"olx_{token}" if token else None


def source_rows(path: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    rows = json.loads(path.read_text("utf-8"))
    by_external: dict[str, list[str]] = {}
    phone_sets: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    invalid_phone_rows = 0
    invalid_url_rows = 0
    for row in rows:
        ext = external_id(row)
        phones = phone_values(row.get("phone"))
        if not ext:
            invalid_url_rows += 1
            continue
        if not phones:
            invalid_phone_rows += 1
            continue
        # OLX tokens are base-62 style and therefore case-sensitive.
        phone_sets[ext].add(tuple(phones))
        current = by_external.setdefault(ext, [])
        for phone in phones:
            if phone not in current:
                current.append(phone)
    conflicts = {key: sorted(map(list, values)) for key, values in phone_sets.items() if len(values) > 1}
    return by_external, {
        "source_rows": len(rows),
        "unique_external_ids": len(by_external),
        "duplicate_rows": len(rows) - len(by_external) - invalid_url_rows - invalid_phone_rows,
        "invalid_url_rows": invalid_url_rows,
        "invalid_phone_rows": invalid_phone_rows,
        "conflicting_external_ids": len(conflicts),
        "conflicts": conflicts,
    }


def merge_unique(current: list[str], incoming: list[str]) -> list[str]:
    return list(dict.fromkeys([*current, *incoming]))


def non_phone_hash(row: dict[str, Any], phone_column: str) -> str:
    payload = {key: value for key, value in row.items() if key != phone_column}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def build_plan(conn, phones_by_external: dict[str, list[str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    matched_external: set[str] = set()
    matched_by_catalog: dict[str, int] = {}
    matched_active_by_catalog: dict[str, int] = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        for catalog, (table, phone_column) in TABLES.items():
            cursor.execute(f"SELECT * FROM {table} WHERE source='olx'")
            matched = 0
            active = 0
            for raw in cursor:
                row = dict(raw)
                key = str(row["external_id"])
                incoming = phones_by_external.get(key)
                if not incoming:
                    continue
                matched_external.add(key)
                matched += 1
                active += row.get("status") == "active"
                current = phone_values(" ".join(row.get(phone_column) or [])) if phone_column == "phones" else phone_values(row.get(phone_column))
                desired = merge_unique(current, incoming)
                current_value = list(row.get(phone_column) or []) if phone_column == "phones" else (row.get(phone_column) or "")
                desired_value: Any = desired if phone_column == "phones" else " ".join(desired)
                plan.append({
                    "catalog": catalog,
                    "table": table,
                    "phone_column": phone_column,
                    "id": row["id"],
                    "external_id": row["external_id"],
                    "operation": row["operation"],
                    "status": row["status"],
                    "url": row.get("url"),
                    "old_value": current_value,
                    "new_value": desired_value,
                    "needs_db_update": current_value != desired_value,
                    "non_phone_hash_before": non_phone_hash(row, phone_column),
                })
            matched_by_catalog[catalog] = matched
            matched_active_by_catalog[catalog] = active
    cross_catalog = defaultdict(list)
    for item in plan:
        cross_catalog[item["external_id"]].append(item["catalog"])
    ambiguous = {key: values for key, values in cross_catalog.items() if len(set(values)) > 1}
    stats = {
        "matched_unique_external_ids": len(matched_external),
        "unmatched_unique_external_ids": len(set(phones_by_external) - matched_external),
        "matched_rows_by_catalog": matched_by_catalog,
        "matched_active_rows_by_catalog": matched_active_by_catalog,
        "cross_catalog_external_ids": len(ambiguous),
        "db_rows_to_update": sum(item["needs_db_update"] for item in plan),
        "db_rows_already_current": sum(not item["needs_db_update"] for item in plan),
    }
    return plan, stats


def apply_database(conn, plan: list[dict[str, Any]]) -> int:
    changed = 0
    with conn.cursor() as cursor:
        for item in plan:
            if not item["needs_db_update"]:
                continue
            cursor.execute(
                f"UPDATE {item['table']} SET {item['phone_column']}=%s WHERE id=%s AND source='olx'",
                (item["new_value"], item["id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"refused non-unique update: {item['catalog']} id={item['id']}")
            changed += 1
    return changed


def verify_database(conn, plan: list[dict[str, Any]]) -> dict[str, int]:
    verified = 0
    non_phone_changes = 0
    wrong_phone = 0
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        for item in plan:
            cursor.execute(f"SELECT * FROM {item['table']} WHERE id=%s", (item["id"],))
            row = dict(cursor.fetchone())
            if row[item["phone_column"]] != item["new_value"]:
                wrong_phone += 1
            elif non_phone_hash(row, item["phone_column"]) != item["non_phone_hash_before"]:
                non_phone_changes += 1
            else:
                verified += 1
    return {"verified_rows": verified, "wrong_phone_rows": wrong_phone, "non_phone_changes": non_phone_changes}


def column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def retry(action, attempts: int = 6):
    for attempt in range(attempts):
        try:
            return action()
        except Exception as exc:
            transient = any(code in str(exc) for code in ("429", "500", "503", "RESOURCE_EXHAUSTED"))
            if not transient or attempt + 1 == attempts:
                raise
            time.sleep(min(32, 2 ** attempt))


def sync_sheets(plan: list[dict[str, Any]]) -> dict[str, Any]:
    if not CREDS.is_file():
        raise RuntimeError("Google service-account credentials are unavailable")
    targets = {
        (item["catalog"], str(item["id"])): " ".join(item["new_value"]) if isinstance(item["new_value"], list) else item["new_value"]
        for item in plan if item["status"] == "active" and item["new_value"]
    }
    client = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
    report: dict[str, Any] = {"cells_updated": 0, "already_current": 0, "target_rows_missing": 0, "by_tab": {}}
    seen: set[tuple[str, str]] = set()
    with SheetsLock("import_olx_phone_export"):
        for catalog, spec in BOOKS.items():
            book = retry(lambda: client.open_by_key(spec["id"]))
            for operation, tab_name in TABS.items():
                sheet = retry(lambda: book.worksheet(tab_name))
                values = retry(lambda: sheet.get_all_values(value_render_option="FORMULA"))
                if not values or "ID" not in values[0] or spec["phone_header"] not in values[0]:
                    raise RuntimeError(f"{catalog}/{tab_name}: expected ID and phone headers; refusing write")
                id_index = values[0].index("ID")
                phone_index = values[0].index(spec["phone_header"])
                phone_column = column_name(phone_index + 1)
                updates = []
                for row_number, row in enumerate(values[1:], 2):
                    listing_id = str(row[id_index]).strip() if len(row) > id_index else ""
                    key = (catalog, listing_id)
                    desired = targets.get(key)
                    if not desired:
                        continue
                    seen.add(key)
                    current = str(row[phone_index]).strip() if len(row) > phone_index else ""
                    merged = " ".join(merge_unique(phone_values(current), phone_values(desired)))
                    if current == merged:
                        report["already_current"] += 1
                    else:
                        updates.append({"range": f"{phone_column}{row_number}", "values": [[merged]]})
                for start in range(0, len(updates), 100):
                    batch = updates[start:start + 100]
                    # gspread qualifies ranges in place.  A transient retry
                    # must receive a fresh payload or the sheet name is
                    # prefixed repeatedly and Google rejects the range.
                    retry(lambda batch=batch: sheet.batch_update(copy.deepcopy(batch), value_input_option="RAW"))
                report["cells_updated"] += len(updates)
                report["by_tab"][f"{catalog}:{operation}"] = len(updates)
    report["target_rows_missing"] = len(set(targets) - seen)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_json", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply-db", action="store_true")
    parser.add_argument("--sync-sheets", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    phones, source_report = source_rows(args.source_json)
    with psycopg2.connect(**DB) as conn:
        plan, match_report = build_plan(conn, phones)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = args.output_dir / f"phone_import_backup_{stamp}.json"
        backup_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str), "utf-8")
        report: dict[str, Any] = {"mode": "apply" if args.apply_db else "dry-run", **source_report, **match_report, "backup": str(backup_path)}
        if args.apply_db:
            report["db_rows_updated"] = apply_database(conn, plan)
            verification = verify_database(conn, plan)
            report["db_verification"] = verification
            if verification["wrong_phone_rows"] or verification["non_phone_changes"]:
                conn.rollback()
                raise RuntimeError(f"verification failed; transaction rolled back: {verification}")
            conn.commit()
        else:
            conn.rollback()
    if args.sync_sheets:
        if not args.apply_db:
            raise RuntimeError("--sync-sheets requires --apply-db")
        report["google_sheets"] = sync_sheets(plan)
    report_path = args.output_dir / f"phone_import_report_{stamp}.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
