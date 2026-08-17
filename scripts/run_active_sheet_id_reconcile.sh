#!/usr/bin/env bash
set -euo pipefail

project_dir="${KYIV_ESTATE_HOME:?}"
cd "$project_dir"
exec "$project_dir/venv/bin/python" "$project_dir/scripts/reconcile_active_sheet_ids.py"
