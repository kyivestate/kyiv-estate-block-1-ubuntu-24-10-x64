set -euo pipefail
PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
LOCK="/tmp/kyiv_estate_commercial_sheets_sync.lock"
mkdir -p "$PROJECT/logs"
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT
cd "$PROJECT"
source venv/bin/activate
python commercial_v1/scripts/sync_commercial_sheets.py >> "$PROJECT/logs/commercial_sheets_sync.log" 2>&1
