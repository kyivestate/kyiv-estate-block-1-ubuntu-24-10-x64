#!/bin/bash
set -euo pipefail

PROJECT="${PROJECT:-$HOME/Projects/real-estate-platform/telegram-bot}"
BACKUP_ROOT="$PROJECT/backups/production"
PG_DUMP="/Applications/Postgres.app/Contents/Versions/latest/bin/pg_dump"
PG_RESTORE="/Applications/Postgres.app/Contents/Versions/latest/bin/pg_restore"
PYTHON="$PROJECT/venv/bin/python"
STAMP="$(date '+%Y%m%d_%H%M%S')"
DATABASE_TMP=""

test -x "$PG_DUMP"
test -x "$PG_RESTORE"
test -x "$PYTHON"
mkdir -p "$BACKUP_ROOT"
umask 077
DATABASE_TMP="$(mktemp "$BACKUP_ROOT/.real_estate_${STAMP}_XXXXXX.dump")"
trap 'test -n "$DATABASE_TMP" && rm -f "$DATABASE_TMP"' EXIT

"$PG_DUMP" --format=custom --no-owner --no-privileges --file="$DATABASE_TMP" -U admin real_estate
"$PG_RESTORE" --list "$DATABASE_TMP" >/dev/null
DATABASE_FILE="$BACKUP_ROOT/real_estate_${STAMP}.dump"
mv "$DATABASE_TMP" "$DATABASE_FILE"
DATABASE_TMP=""
shasum -a 256 "$DATABASE_FILE" > "$DATABASE_FILE.sha256"
SHEETS_BACKUP=""
# A Sheets writer may legitimately be active when the nightly job starts.
# Retry on a fresh temporary directory, then publish only a complete snapshot.
for attempt in $(seq 1 30); do
  CANDIDATE="$BACKUP_ROOT/.sheets_${STAMP}_${attempt}.partial"
  if "$PYTHON" "$PROJECT/parser_v2/scripts/backup_sheets.py" --directory "$CANDIDATE"; then
    SHEETS_BACKUP="$BACKUP_ROOT/sheets_${STAMP}"
    mv "$CANDIDATE" "$SHEETS_BACKUP"
    break
  fi
  rm -rf "$CANDIDATE"
  sleep 60
done
test -n "$SHEETS_BACKUP"
touch "$PROJECT/.last_production_backup"
find "$BACKUP_ROOT" -type f \( -name '*.dump' -o -name '*.sha256' \) -mtime +30 -delete
find "$BACKUP_ROOT" -type d -name 'sheets_*' -mtime +30 -exec rm -rf {} +
printf '%s backup=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$DATABASE_FILE" >> "$PROJECT/logs/backup.log"
