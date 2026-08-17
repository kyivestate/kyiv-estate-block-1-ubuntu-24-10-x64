#!/usr/bin/env bash
set -euo pipefail
ROOT="${KYIV_ESTATE_HOME:?}"
cd "$ROOT"
exec "$ROOT/venv/bin/python" -m cleaning.backfill_inactive --batch-size 250 --batches 10
