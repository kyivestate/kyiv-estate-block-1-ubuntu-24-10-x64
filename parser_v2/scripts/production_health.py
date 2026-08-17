import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2


PROJECT = Path("/Users/admin/Projects/real-estate-platform/telegram-bot")
SERVICES = (
    "com.realestate.incremental_parser",
    "com.realestate.houses.incremental_parser",
    "com.realestate.commercial.incremental_parser",
    "com.realestate.status_checks",
    "com.realestate.active_sheet_reconcile",
    "com.realestate.backup",
    "com.realestate.guard",
)
FULL_COVERAGE_LOCKS = (
    Path("/tmp/kyiv_estate_apartments_full_backfill.lock"),
    Path("/tmp/kyiv_estate_houses_full_backfill.lock"),
    Path("/tmp/kyiv_estate_commercial_full_backfill.lock"),
)


def age_seconds(path):
    try:
        return round(time.time() - Path(path).stat().st_mtime)
    except FileNotFoundError:
        return None


def service_state(label):
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout
    state = re.search(r"^\s*state = (.+)$", output, re.MULTILINE)
    pid = re.search(r"^\s*pid = (\d+)", output, re.MULTILINE)
    last_exit_code = re.search(r"^\s*last exit code = (\d+)", output, re.MULTILINE)
    return {
        "state": state.group(1).strip() if state else "missing",
        "pid": int(pid.group(1)) if pid else None,
        "last_exit_code": int(last_exit_code.group(1)) if last_exit_code else None,
        "exit_code": result.returncode,
    }


def database_report():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin", connect_timeout=10)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status, count(*) FROM active_listings GROUP BY status ORDER BY status")
            statuses = dict(cursor.fetchall())
            cursor.execute("""SELECT count(*) FROM (
                SELECT source, external_id
                FROM active_listings
                GROUP BY source, external_id
                HAVING count(*) > 1
            ) duplicates""")
            duplicate_source_external = cursor.fetchone()[0]
            cursor.execute("""SELECT count(*)
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                  AND (ai_title IS NULL OR length(trim(ai_title)) < 18
                       OR lower(trim(ai_title)) IN ('опис','добре','ок','none','null','title','назва')
                       OR ai_title ~ '^#?[0-9]+'
                       OR ai_description IS NULL OR length(trim(ai_description)) < 100
                       OR lower(trim(ai_description)) IN ('опис','добре','ок','none','null','description')
                       OR ai_description ~ '^#?[0-9]+')""")
            active_without_ai = cursor.fetchone()[0]
            cursor.execute("""SELECT count(*) FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                  AND floor IS NOT NULL AND floors_total IS NOT NULL AND floor > floors_total""")
            active_floor_invalid = cursor.fetchone()[0]
            cursor.execute("""SELECT count(*) FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                  AND lower(coalesce(ai_description,'')) ~ '(комісі|ріелтор|риелтор|брокер|агент|власник|контакт|телефон|дзвон|звон|пишіть|звертайтеся|не турбувати)'""")
            active_ai_policy_violations = cursor.fetchone()[0]
            cursor.execute("""SELECT source, operation, count(*)
                FROM active_listings
                WHERE status='active' AND source NOT LIKE 'findly%%'
                GROUP BY source, operation
                ORDER BY source, operation""")
            active_by_source = [
                {"source": source, "operation": operation, "count": count}
                for source, operation, count in cursor.fetchall()
            ]
            cursor.execute("SELECT max(updated_at), max(parsed_at) FROM active_listings WHERE source NOT LIKE 'findly%%'")
            updated_at, parsed_at = cursor.fetchone()
            try:
                cursor.execute("""SELECT listing.source, count(*), min(checks.checked_at), max(checks.checked_at),
                    count(*) FILTER (WHERE checks.checked_at IS NULL),
                    count(*) FILTER (WHERE checks.checked_at IS NULL OR checks.checked_at < NOW() - INTERVAL '72 hours')
                    FROM active_listings listing
                    LEFT JOIN listing_status_checks checks ON checks.listing_id=listing.id
                    WHERE listing.status='active' AND listing.source IN ('olx','rieltor')
                    GROUP BY listing.source ORDER BY listing.source""")
                status_checks = [
                    {
                        "source": source,
                        "active": count,
                        "oldest_checked_at": oldest.isoformat() if oldest else None,
                        "newest_checked_at": newest.isoformat() if newest else None,
                        "never_checked": never_checked,
                        "not_checked_within_72h": not_checked_within_72h,
                    }
                    for source, count, oldest, newest, never_checked, not_checked_within_72h in cursor.fetchall()
                ]
            except psycopg2.Error:
                conn.rollback()
                status_checks = []
    finally:
        conn.close()
    return {
        "statuses": statuses,
        "duplicate_source_external": duplicate_source_external,
        "active_without_ai": active_without_ai,
        "active_floor_invalid": active_floor_invalid,
        "active_ai_policy_violations": active_ai_policy_violations,
        "active_by_source": active_by_source,
        "last_updated_at": updated_at.isoformat() if updated_at else None,
        "last_parsed_at": parsed_at.isoformat() if parsed_at else None,
        "status_checks": status_checks,
    }


def report():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": {label: service_state(label) for label in SERVICES},
        "files": {
            "incremental_log_age_seconds": age_seconds(PROJECT / "logs/incremental_parser.log"),
            "guard_log_age_seconds": age_seconds(PROJECT / "logs/guard.log"),
            "quality_filter_age_seconds": age_seconds(PROJECT / ".last_qfilter"),
            "backup_age_seconds": age_seconds(PROJECT / ".last_production_backup"),
        },
        "full_coverage_in_progress": any(path.is_dir() for path in FULL_COVERAGE_LOCKS),
        "database": database_report(),
    }


def strict_issues(data):
    issues = []
    incremental = data["services"]["com.realestate.incremental_parser"]
    guard = data["services"]["com.realestate.guard"]
    if incremental["state"] == "missing":
        issues.append("service_missing:com.realestate.incremental_parser")
    if incremental["last_exit_code"] not in (None, 0):
        issues.append("service_failed:com.realestate.incremental_parser")
    for label in (
        "com.realestate.houses.incremental_parser",
        "com.realestate.commercial.incremental_parser",
        "com.realestate.status_checks",
        "com.realestate.active_sheet_reconcile",
        "com.realestate.backup",
    ):
        service = data["services"][label]
        if service["state"] == "missing":
            issues.append(f"service_missing:{label}")
        if service["last_exit_code"] not in (None, 0):
            issues.append(f"service_failed:{label}")
    if guard["state"] != "running":
        issues.append("service_not_running:com.realestate.guard")
    if guard["last_exit_code"] not in (None, 0):
        issues.append("service_failed:com.realestate.guard")
    log_age = data["files"]["incremental_log_age_seconds"]
    # During a complete catalog pass the incremental process intentionally
    # yields its lock; a quiet incremental log is therefore expected.
    if (log_age is None or log_age > 3900) and not data["full_coverage_in_progress"]:
        issues.append("incremental_log_stale")
    backup_age = data["files"]["backup_age_seconds"]
    # The production snapshot runs daily at 03:15 and normally finishes in a
    # few minutes.  A 26-hour ceiling catches a missed or incomplete backup
    # without alerting merely because the job is between scheduled runs.
    if backup_age is None or backup_age > 26 * 60 * 60:
        issues.append("backup_stale")
    database = data["database"]
    if not database["statuses"].get("active", 0):
        issues.append("no_active_listings")
    if database["duplicate_source_external"]:
        issues.append("duplicate_source_external")
    if database["active_floor_invalid"]:
        issues.append("active_floor_invalid")
    if database["active_without_ai"]:
        issues.append("active_without_ai")
    if database["active_ai_policy_violations"]:
        issues.append("active_ai_policy_violations")
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    data = report()
    issues = strict_issues(data)
    data["strict_issues"] = issues
    rendered = json.dumps(data, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        os.chmod(output, 0o600)
        print(f"HEALTH_REPORT={output.resolve()}")
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
