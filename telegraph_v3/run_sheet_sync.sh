#!/usr/bin/env bash
set -euo pipefail

project_dir="${KYIV_ESTATE_HOME:?}"
log_dir="$project_dir/logs"
mkdir -p "$log_dir"
exec "$project_dir/venv/bin/python" "$project_dir/telegraph_v3/sync_to_sheets.py" \
  >> "$log_dir/block3_sheet_sync.log" 2>&1
