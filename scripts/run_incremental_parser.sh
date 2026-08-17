#!/bin/bash
set -euo pipefail
LOCKDIR=/tmp/kyiv_estate_incremental_parser.lock
FULL_LOCK=/tmp/kyiv_estate_apartments_full_backfill.lock
if [ -d "$FULL_LOCK" ]; then exit 0; fi
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  OWNER="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
  if [[ "$OWNER" =~ ^[0-9]+$ ]] && kill -0 "$OWNER" 2>/dev/null; then exit 0; fi
  rm -f "$LOCKDIR/pid"
  rmdir "$LOCKDIR" 2>/dev/null || exit 0
  mkdir "$LOCKDIR" || exit 0
fi
printf '%s\n' "$$" > "$LOCKDIR/pid"
trap 'rm -f "$LOCKDIR/pid"; rmdir "$LOCKDIR"' EXIT INT TERM
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
export OLX_MAX_PAGES=1
export RIELTOR_MAX_PAGES=1
run_pipeline_with_deadline() {
  python -m parser_v2.pipeline_v2 --source all --operation all --property-scope apartments --no-rebuild-sheets --no-dead-check &
  local pid=$!
  local elapsed=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$elapsed" -ge 900 ]; then
      echo "pipeline_timeout_seconds=$elapsed pid=$pid" >&2
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  wait "$pid"
}
run_pipeline_with_deadline
python parser_v2/scripts/deduplicate_listings.py
# Retry a small, balanced batch of previously transient apartment failures.
# It acquires the pipeline lock itself, so a late/overlapping run safely skips.
python -m parser_v2.scripts.retry_failed_urls --limit 80 --max-retries 3
python parser_v2/scripts/fill_new_listings.py
nohup python parser_v2/scripts/check_listing_statuses.py >> logs/status_checks.log 2>&1 &
main_synced=0
for attempt in 1 2 3 4 5 6; do
  if python parser_v2/scripts/run_all.py; then
    main_synced=1
    break
  fi
  sleep $((attempt * 60))
done
if [ "$main_synced" -ne 1 ]; then
  exit 1
fi
# Lifecycle is not an input to Active data.  Its oversized legacy workbook must
# never keep the 30-minute apartment parser in a failing/retry loop.
if ! python parser_v2/scripts/sync_listing_lifecycle.py; then
  echo "lifecycle_sync_skipped: workbook size/API error; Active sync succeeded" >&2
fi
exit 0
