#!/usr/bin/env bash
set -euo pipefail
project_dir="${KYIV_ESTATE_HOME:?}"
mkdir -p "$project_dir/logs"
exec "$project_dir/venv/bin/python" "$project_dir/telegraph_v3/page_catalog.py" \
  >> "$project_dir/logs/page_catalog.log" 2>&1
