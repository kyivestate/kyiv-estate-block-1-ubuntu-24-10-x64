"""Archive active houses that do not meet the current intake policy.

This is a one-time, explicit migration. It never hard-deletes: every affected
row is first copied to the Archive workbook and ``cleaning_archives``, then it
is removed from Active by exact ID and marked ``inactive`` in PostgreSQL.
"""
from __future__ import annotations

import argparse
import json

import psycopg2.extras

from cleaning.service import archive_tabs, attach_user_notes, book, remove_from_active, row_values
from houses_v1.persistence import get_conn
from parser_v2.services.kyiv_region import is_kyiv_region
from parser_v2.services.sheets_lock import SheetsLock


def policy_reason(row: dict) -> str | None:
    minimum = 2_000 if row["operation"] == "rent" else 100_000
    price = row.get("price_usd")
    price_fails = price is None or float(price) < minimum
    location_text = " ".join(str(row.get(key) or "") for key in ("city", "district", "street", "title", "description"))
    location_fails = not is_kyiv_region(location_text)
    reasons: list[str] = []
    if price_fails:
        reasons.append(f"usd_below_{minimum}" if price is not None else "usd_missing")
    if location_fails:
        reasons.append("outside_kyiv_region")
    return "policy_houses_" + "_".join(reasons) if reasons else None


def candidates(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM houses_listings WHERE status='active' ORDER BY id")
        return [dict(row) for row in cur.fetchall() if policy_reason(dict(row))]


def report(rows: list[dict]) -> None:
    summary = {"rent": 0, "buy": 0, "price": 0, "location": 0}
    for row in rows:
        summary[row["operation"]] += 1
        reason = policy_reason(row) or ""
        summary["price"] += "usd_" in reason
        summary["location"] += "outside_kyiv_region" in reason
    print(json.dumps({"candidates": len(rows), **summary}, ensure_ascii=False))


def apply(rows: list[dict]) -> None:
    if not rows:
        return
    with get_conn() as conn, SheetsLock("houses_policy_archive"):


        rows = candidates(conn)
        report(rows)
        if not rows:
            return
        archive_book = book()
        archive_tabs(archive_book)
        rows = attach_user_notes(conn, "houses", rows)
        for operation, tab in (("rent", "Будинки - Оренда"), ("buy", "Будинки - Продаж")):
            scoped = [row for row in rows if row["operation"] == operation]
            if not scoped:
                continue
            worksheet = archive_book.worksheet(tab)
            already_archived = {str(value).strip() for value in worksheet.col_values(4)[1:] if str(value).strip()}
            append = [row for row in scoped if str(row["id"]) not in already_archived]
            if append:
                worksheet.append_rows(
                    [row_values("houses", row, policy_reason(row) or "policy") for row in append],
                    value_input_option="USER_ENTERED",
                )
        with conn.cursor() as cur:
            for row in rows:
                reason = policy_reason(row) or "policy"
                cur.execute(
                    """INSERT INTO cleaning_archives(catalog,listing_id,reason,snapshot)
                       VALUES('houses',%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (row["id"], reason, json.dumps(row, ensure_ascii=False, default=str)),
                )
                cur.execute(
                    "UPDATE houses_listings SET status='inactive', updated_at=NOW() WHERE id=%s AND status='active'",
                    (row["id"],),
                )
        conn.commit()


        for operation in ("rent", "buy"):
            identifiers = [row["id"] for row in rows if row["operation"] == operation]
            if identifiers:
                remove_from_active("houses", operation, identifiers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the archival; without it only print the count")
    args = parser.parse_args()
    with get_conn() as conn:
        rows = candidates(conn)
    report(rows)
    if args.apply:
        apply(rows)


if __name__ == "__main__":
    main()
