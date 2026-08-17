#!/usr/bin/env bash
set -euo pipefail
PROJECT="${KYIV_ESTATE_HOME:?}"
FULL_LOCK=/tmp/kyiv_estate_houses_full_backfill.lock
INCREMENTAL_LOCK=/tmp/kyiv_estate_houses_incremental.lock
APARTMENTS_FULL_LOCK=/tmp/kyiv_estate_apartments_full_backfill.lock
mkdir -p "$PROJECT/logs"
while [ -d "$INCREMENTAL_LOCK" ]; do sleep 30; done
if ! mkdir "$FULL_LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$FULL_LOCK"' EXIT INT TERM
cd "$PROJECT"
source venv/bin/activate
export OLX_MAX_PAGES=999
export RIELTOR_MAX_PAGES=999
python -m houses_v1.pipeline --source olx --operation all --refresh-existing
while [ -d "$APARTMENTS_FULL_LOCK" ]; do sleep 60; done
python -m houses_v1.pipeline --source rieltor --operation all --refresh-existing
python -m houses_v1.refresh_ai
python -m houses_v1.sync_sheets
python -m houses_v1.audit
