set -euo pipefail

PROJECT=/Users/admin/Projects/real-estate-platform/telegram-bot
LOCKDIR=/tmp/kyiv_estate_findly_incremental.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCKDIR"' EXIT INT TERM

cd "$PROJECT"
source venv/bin/activate
python -m findly_v1.pipeline --operation all
python -m findly_v1.refresh_ai
python -m findly_v1.audit
python -m findly_v1.sync_sheets
