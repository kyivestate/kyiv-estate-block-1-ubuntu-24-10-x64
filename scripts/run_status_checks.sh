#!/usr/bin/env bash
set -euo pipefail

PROJECT="${KYIV_ESTATE_HOME:?}"
cd "$PROJECT"
source venv/bin/activate

OLX_LIMIT=1000
RIELTOR_LIMIT=300
if [ -d /tmp/kyiv_estate_apartments_full_backfill.lock ] || [ -d /tmp/kyiv_estate_houses_full_backfill.lock ] || [ -d /tmp/kyiv_estate_commercial_full_backfill.lock ]; then
  RIELTOR_LIMIT=0
fi

exec python parser_v2/scripts/check_listing_statuses.py --olx-limit "$OLX_LIMIT" --rieltor-limit "$RIELTOR_LIMIT"
