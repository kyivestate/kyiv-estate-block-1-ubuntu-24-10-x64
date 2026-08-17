set -euo pipefail

PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$PROJECT"
exec "$PROJECT/venv/bin/python" telegraph_v3/sync_to_sheets.py
