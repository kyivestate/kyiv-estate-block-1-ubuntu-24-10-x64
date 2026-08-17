#!/usr/bin/env bash
set -euo pipefail

PROJECT=${KYIV_ESTATE_HOME:?}
LOCKDIR=/tmp/kyiv_estate_findly_incremental.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCKDIR"' EXIT INT TERM

cd "$PROJECT"
source venv/bin/activate
python -m findly_v1.pipeline --operation all
python -m findly_v1.refresh_ai
python -m findly_v1.audit
python -m findly_v1.sync_sheets
