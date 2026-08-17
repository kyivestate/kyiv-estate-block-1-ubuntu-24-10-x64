#!/bin/bash
set -euo pipefail
LOCK=/tmp/kyiv_estate_cleaning.lock
backfill_active=0
for full_lock in /tmp/kyiv_estate_apartments_full_backfill.lock /tmp/kyiv_estate_houses_full_backfill.lock /tmp/kyiv_estate_commercial_full_backfill.lock; do
  [ -d "$full_lock" ] && backfill_active=1
done
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK"' EXIT INT TERM
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
if [ "$backfill_active" -eq 1 ]; then
  # Keep availability checks alive during long full crawls without doubling
  # the normal source load.  The normal per-scope limit returns automatically
  # as soon as all full-backfill locks disappear.
  export CLEANING_LIMIT_PER_SCOPE="${CLEANING_LIMIT_DURING_BACKFILL:-10}"
  echo "cleaning_mode=reduced_during_full_backfill limit_per_scope=$CLEANING_LIMIT_PER_SCOPE"
fi
python -m cleaning.service
