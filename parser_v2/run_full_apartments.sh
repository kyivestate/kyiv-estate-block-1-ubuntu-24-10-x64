#!/bin/bash
set -euo pipefail
PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
FULL_LOCK=/tmp/kyiv_estate_apartments_full_backfill.lock
INCREMENTAL_LOCK=/tmp/kyiv_estate_incremental_parser.lock
mkdir -p "$PROJECT/logs"
while [ -d "$INCREMENTAL_LOCK" ]; do sleep 30; done
if ! mkdir "$FULL_LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$FULL_LOCK"' EXIT INT TERM
cd "$PROJECT"
source venv/bin/activate
export OLX_MAX_PAGES=999
export RIELTOR_MAX_PAGES=999
python -m parser_v2.pipeline_v2 --source all --operation all --property-scope apartments --no-rebuild-sheets --no-dead-check
python parser_v2/scripts/deduplicate_listings.py
python parser_v2/scripts/fill_new_listings.py
python parser_v2/scripts/run_all.py
# Lifecycle is a reporting mirror.  A full Active-data collection must not be
# marked failed merely because the legacy Lifecycle workbook has hit its size limit.
if ! python parser_v2/scripts/sync_listing_lifecycle.py; then
  echo "lifecycle_sync_skipped: workbook size/API error; Active data is intact" >&2
fi
# Resume the lightweight apartment cycle and hand the next full pass to houses.
launchctl bootstrap "gui/$(id -u)" /Users/admin/Library/LaunchAgents/com.realestate.incremental_parser.plist 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" /Users/admin/Library/LaunchAgents/com.realestate.houses.full_backfill.plist 2>/dev/null || true
