set -euo pipefail

project_dir="/Users/admin/Projects/real-estate-platform/telegram-bot"
log_dir="$project_dir/logs"
mkdir -p "$log_dir"
exec "$project_dir/venv/bin/python" "$project_dir/telegraph_v3/telegraph_batch.py" \
  --limit 100 \
  --media-mode archive \
  --publish-workers 1 \
  --no-sync \
  >> "$log_dir/block3_continuous_publish.log" 2>&1
