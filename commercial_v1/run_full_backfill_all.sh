#!/usr/bin/env bash
set -euo pipefail
PROJECT="${KYIV_ESTATE_HOME:?}"
FULL_LOCK="/tmp/kyiv_estate_commercial_full_backfill.lock"
SUPERVISOR_LOCK="/tmp/kyiv_estate_commercial_full_backfill_supervisor.lock"
INCREMENTAL_LOCK="/tmp/kyiv_estate_commercial_incremental.lock"
APARTMENTS_FULL_LOCK="/tmp/kyiv_estate_apartments_full_backfill.lock"
HOUSES_FULL_LOCK="/tmp/kyiv_estate_houses_full_backfill.lock"
mkdir -p "$PROJECT/logs"

acquire_full_lock() {
  while [ -d "$INCREMENTAL_LOCK" ]; do sleep 30; done
  if ! mkdir "$FULL_LOCK" 2>/dev/null; then exit 0; fi
}

if ! mkdir "$SUPERVISOR_LOCK" 2>/dev/null; then
  exit 0
fi

release_full_lock() {
  rmdir "$FULL_LOCK" 2>/dev/null || true
}

release_locks() {
  release_full_lock
  rmdir "$SUPERVISOR_LOCK" 2>/dev/null || true
}

trap 'release_locks' EXIT INT TERM
cd "$PROJECT"
source venv/bin/activate
acquire_full_lock
for SOURCE in olx; do
  for OPERATION in rent buy; do
    python commercial_v1/scripts/full_backfill.py --source "$SOURCE" --operation "$OPERATION" --until-complete --restart --refresh-existing \
      > "logs/commercial_backfill_${SOURCE}_${OPERATION}.log" 2>&1 &
  done
done
wait
release_full_lock
while [ -d "$APARTMENTS_FULL_LOCK" ] || [ -d "$HOUSES_FULL_LOCK" ]; do
  sleep 60
done
acquire_full_lock
for SOURCE in rieltor; do
  for OPERATION in rent buy; do
    python commercial_v1/scripts/full_backfill.py --source "$SOURCE" --operation "$OPERATION" --until-complete --restart --refresh-existing \
      > "logs/commercial_backfill_${SOURCE}_${OPERATION}.log" 2>&1 &
  done
done
wait
release_full_lock
if ! python commercial_v1/scripts/sync_commercial_sheets.py; then
  echo "commercial_sheet_sync_deferred: Google Sheets write failed; backfill is retained in PostgreSQL" >&2
fi
python commercial_v1/scripts/health.py
