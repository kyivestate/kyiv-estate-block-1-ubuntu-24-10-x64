#!/bin/bash
set -euo pipefail
PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
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
  # Google Sheets is an output, never a prerequisite for OLX/Rieltor intake.
  # Keep the production database fresh if the workbook is rate- or size-limited.
  if ! python commercial_v1/scripts/sync_commercial_sheets.py; then
    echo "commercial_sheet_sync_deferred: Google Sheets write failed; parser data is committed" >&2
  fi
fi
python commercial_v1/scripts/health.py >> "$LOG" 2>&1
