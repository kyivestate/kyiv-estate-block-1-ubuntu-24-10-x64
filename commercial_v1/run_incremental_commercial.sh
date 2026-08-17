#!/usr/bin/env bash
set -euo pipefail
PROJECT="${KYIV_ESTATE_HOME:?}"
LOCK="/tmp/kyiv_estate_commercial_incremental.lock"
LOG="$PROJECT/logs/commercial_incremental.log"
mkdir -p "$PROJECT/logs"
if [ -d /tmp/kyiv_estate_commercial_full_backfill.lock ]; then
  exit 0
fi
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT
cd "$PROJECT"
source venv/bin/activate
python commercial_v1/scripts/run_commercial.py --max-listings "${COMMERCIAL_MAX_LISTINGS_PER_SCOPE:-25}"
if [ -f commercial_v1/.sheets.json ]; then
  if ! python commercial_v1/scripts/sync_commercial_sheets.py; then
    echo "commercial_sheet_sync_deferred: Google Sheets write failed; parser data is committed" >&2
  fi
fi
python commercial_v1/scripts/health.py >> "$LOG" 2>&1
