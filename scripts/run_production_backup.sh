#!/usr/bin/env bash
set -euo pipefail

PROJECT="${KYIV_ESTATE_HOME:?}"
BACKUP_ROOT="$PROJECT/backups/production"
PG_DUMP="$(command -v pg_dump)"
PG_RESTORE="$(command -v pg_restore)"
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

"$PG_DUMP" --format=custom --no-owner --no-privileges --file="$DATABASE_TMP" --host="${PG_HOST:-127.0.0.1}" --port="${PG_PORT:-5432}" --username="${PG_USER:?}" "${PG_DBNAME:?}"
"$PG_RESTORE" --list "$DATABASE_TMP" >/dev/null
DATABASE_FILE="$BACKUP_ROOT/real_estate_${STAMP}.dump"
mv "$DATABASE_TMP" "$DATABASE_FILE"
DATABASE_TMP=""
sha256sum "$DATABASE_FILE" > "$DATABASE_FILE.sha256"
SHEETS_BACKUP=""
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
find "$BACKUP_ROOT" -type f \( -name '*.dump' -o -name '*.sha256' \) -mtime +14 -delete
find "$BACKUP_ROOT" -type d -name 'sheets_*' -mtime +14 -exec rm -rf {} +
printf '%s backup=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$DATABASE_FILE" >> "$PROJECT/logs/backup.log"
