#!/bin/zsh
set -euo pipefail
project_dir="/Users/admin/Projects/real-estate-platform/telegram-bot"
mkdir -p "$project_dir/logs"
exec "$project_dir/venv/bin/python" "$project_dir/telegraph_v3/page_catalog.py" \
  >> "$project_dir/logs/page_catalog.log" 2>&1
