set -euo pipefail
PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
SOURCE="$1"
OPERATION="$2"
LOCK="/tmp/kyiv_estate_commercial_backfill_${SOURCE}_${OPERATION}.lock"
mkdir -p "$PROJECT/logs"
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT
cd "$PROJECT"
source venv/bin/activate
python commercial_v1/scripts/full_backfill.py --source "$SOURCE" --operation "$OPERATION" --pages 1 --until-complete
