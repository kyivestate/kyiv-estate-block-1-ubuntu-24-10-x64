#!/bin/bash
set -euo pipefail
LOCKDIR=/tmp/kyiv_estate_houses_incremental.lock
FULL_LOCK=/tmp/kyiv_estate_houses_full_backfill.lock
if [ -d "$FULL_LOCK" ]; then exit 0; fi
if ! mkdir "$LOCKDIR" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCKDIR"' EXIT INT TERM
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
export OLX_MAX_PAGES=1 RIELTOR_MAX_PAGES=1
python -m houses_v1.pipeline --source all --operation all
python -m houses_v1.refresh_ai
python -m houses_v1.sync_sheets
