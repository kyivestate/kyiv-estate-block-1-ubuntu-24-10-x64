set -euo pipefail
ROOT="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$ROOT"
exec "$ROOT/venv/bin/python" -m manual_ingest
