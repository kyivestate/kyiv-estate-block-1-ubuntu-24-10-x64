#!/bin/zsh
# Independent Sheet writer.  It never blocks the Telegraph publishing queue.
set -euo pipefail

project_dir="/Users/admin/Projects/real-estate-platform/telegram-bot"
log_dir="$project_dir/logs"
mkdir -p "$log_dir"
exec "$project_dir/venv/bin/python" "$project_dir/telegraph_v3/sync_to_sheets.py" \
  >> "$log_dir/block3_sheet_sync.log" 2>&1
