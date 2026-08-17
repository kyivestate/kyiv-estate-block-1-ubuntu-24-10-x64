#!/bin/zsh
set -euo pipefail

project_dir="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$project_dir"
exec "$project_dir/venv/bin/python" "$project_dir/scripts/reconcile_active_sheet_ids.py"
