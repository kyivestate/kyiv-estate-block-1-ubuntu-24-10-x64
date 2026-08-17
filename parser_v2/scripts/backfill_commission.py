"""Evidence-based repair of commission values in every active production contour."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser_v2.services.commission import normalize_commission

DB = dict(host="localhost", port=5432, dbname="real_estate", user="admin")
TABLES = (
    ("parser_v2_normalized_listings", "commission", "id", False),
    ("active_listings", "commission", "id", True),
    ("houses_normalized_listings", "commission", "id", False),
    ("houses_listings", "commission", "id", True),
    ("commercial_listings", "commission_text", "id", True),
)


def exists(cursor, table: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cursor.fetchone()[0] is not None


def repair(cursor, table: str, field: str, primary_key: str, has_status: bool, apply: bool) -> tuple[int, int, int]:
    where = " WHERE status='active'" if has_status else ""
    cursor.execute(f"SELECT {primary_key}, {field}, title, description FROM {table}{where}")
    changes: list[tuple[str, int]] = []
    extracted = 0
    total = 0
    for row in cursor.fetchall():
        total += 1
        value = normalize_commission(row[1], f"{row[2] or ''} {row[3] or ''}")
        if value != (row[1] or "").strip():
            changes.append((value, row[0]))
            if value not in {"Не вказано", "Комісія: умови уточнюються"}:
                extracted += 1
    if apply and changes:
        psycopg2.extras.execute_batch(cursor, f"UPDATE {table} SET {field}=%s, updated_at=NOW() WHERE {primary_key}=%s", changes, page_size=1000)
    return total, len(changes), extracted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the verified normalized values")
    args = parser.parse_args()
    report = []
    with psycopg2.connect(**DB) as connection, connection.cursor() as cursor:
        for item in TABLES:
            table, field, primary_key, has_status = item
            if not exists(cursor, table):
                continue
            total, changed, extracted = repair(cursor, *item, apply=args.apply)
            report.append({"table": table, "scanned": total, "changed": changed, "explicitly_extracted": extracted})
        if not args.apply:
            connection.rollback()
    for item in report:
        print("{table}: scanned={scanned} changed={changed} explicitly_extracted={explicitly_extracted}".format(**item))


if __name__ == "__main__":
    main()
