#!/bin/bash
set -euo pipefail
ROOT="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$ROOT"
exec "$ROOT/venv/bin/python" -m cleaning.backfill_inactive --batch-size 250 --batches 10
