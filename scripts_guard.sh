#!/usr/bin/env bash
set -uo pipefail

PROJECT="${KYIV_ESTATE_HOME:?}"
export PGPASSWORD="${PG_PASSWORD:-${POSTGRES_PASSWORD:-}}"
LOCKDIR=/tmp/kyiv_estate_guard.lock

if ! mkdir "$LOCKDIR" 2>/dev/null; then
  OWNER="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
  if [[ "$OWNER" =~ ^[0-9]+$ ]] && kill -0 "$OWNER" 2>/dev/null; then
    exit 0
  fi
  rm -f "$LOCKDIR/pid"
  rmdir "$LOCKDIR" 2>/dev/null || exit 0
  mkdir "$LOCKDIR" || exit 0
fi

printf '%s\n' "$$" > "$LOCKDIR/pid"
trap 'rm -f "$LOCKDIR/pid"; rmdir "$LOCKDIR"' EXIT INT TERM
cd "$PROJECT" || exit 1
PYTHON="$PROJECT/venv/bin/python"
test -x "$PYTHON" || exit 1

log_event() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> logs/guard.log
}

db_count() {
  "$PYTHON" - "$1" <<'PY'
import sys
import psycopg2

try:
    connection = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin", connect_timeout=10)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sys.argv[1])
            print(int(cursor.fetchone()[0]))
    finally:
        connection.close()
except Exception:
    print(0)
PY
}

pipeline_running() {
  "$PYTHON" - <<'PY'
import fcntl
import os
import sys

fd = os.open('/tmp/kyiv_estate_pipeline_v2.lock', os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)
else:
    fcntl.flock(fd, fcntl.LOCK_UN)
    sys.exit(1)
finally:
    os.close(fd)
PY
}

worker_count() {
  pgrep -f "$1" 2>/dev/null | wc -l | tr -d '[:space:]'
}

sheets_writer_running() {
  pgrep -f '[r]un_all.py|[s]ync_listing_lifecycle.py' >/dev/null 2>&1
}

background_ready() {
  ! pipeline_running && ! sheets_writer_running && ! pgrep -f '[c]heck_listing_statuses.py' >/dev/null 2>&1
}

AI_QUERY="SELECT count(*) FROM active_listings WHERE status='active' AND source NOT LIKE 'findly%' AND description IS NOT NULL AND LENGTH(TRIM(description))>40 AND (ai_title IS NULL OR LENGTH(TRIM(ai_title))<18 OR LOWER(TRIM(ai_title)) IN ('опис','добре','ок','none','null','title','назва') OR ai_title ~ '^#?[0-9]+' OR ai_description IS NULL OR LENGTH(TRIM(ai_description))<100 OR LOWER(TRIM(ai_description)) IN ('опис','добре','ок','none','null','description') OR ai_description ~ '^#?[0-9]+' OR lower(ai_description) ~ '(комісі|ріелтор|риелтор|брокер|агент|власник|контакт|телефон|дзвон|звон|пишіть|звертайтеся|не турбувати)')"
AI_FULL_REBUILD_QUERY="SELECT count(*) FROM active_listings listing LEFT JOIN ai_content_rebuilds rebuilt ON rebuilt.listing_id=listing.id WHERE listing.status='active' AND listing.source NOT LIKE 'findly%' AND listing.description IS NOT NULL AND LENGTH(TRIM(listing.description))>=40 AND (rebuilt.version IS NULL OR rebuilt.version<2)"
REPARSE_QUERY="SELECT count(*) FROM active_listings WHERE status='active' AND source IN ('olx','rieltor') AND url LIKE 'http%' AND (rooms IS NULL OR area IS NULL OR floor IS NULL OR district IS NULL OR district='' OR description IS NULL OR LENGTH(TRIM(COALESCE(description,'')))<40)"
BACKFILL_QUERY="SELECT count(*) FROM active_listings listing WHERE status='active' AND source IN ('olx','rieltor') AND NOT EXISTS (SELECT 1 FROM listing_enrichment_attempts attempt WHERE attempt.listing_id=listing.id AND attempt.raw_checked_at >= NOW() - INTERVAL '14 days') AND (rooms IS NULL OR area IS NULL OR district IS NULL OR district='' OR street IS NULL OR street='' OR metro_station IS NULL OR metro_station='' OR photo_url IS NULL OR photo_url='' OR description IS NULL OR LENGTH(TRIM(COALESCE(description,'')))<40 OR (property_type='Квартира' AND (floor IS NULL OR floors_total IS NULL)) OR (property_type='Будинок' AND floors_total IS NULL))"
LIVE_ENRICHMENT_QUERY="SELECT count(*) FROM active_listings listing LEFT JOIN listing_live_enrichment_attempts attempt ON attempt.listing_id=listing.id WHERE listing.status='active' AND listing.source IN ('olx','rieltor') AND listing.url LIKE 'http%' AND (attempt.checked_at IS NULL OR attempt.checked_at < NOW() - INTERVAL '7 days') AND (listing.rooms IS NULL OR listing.area IS NULL OR listing.floor IS NULL OR listing.floors_total IS NULL OR listing.district IS NULL OR listing.district='' OR listing.street IS NULL OR listing.street='' OR listing.metro_station IS NULL OR listing.metro_station='' OR listing.photo_url IS NULL OR listing.photo_url='' OR listing.description IS NULL OR LENGTH(TRIM(COALESCE(listing.description,'')))<40 OR (listing.source='rieltor' AND (listing.agent_name IS NULL OR listing.agent_name='' OR listing.agent_phone IS NULL OR listing.agent_phone='')))"

while true; do
  REBUILD_N="$(worker_count '[r]ebuild_ai_content.py')"
  FAST_N="$(worker_count '[g]enerate_ai_fast.py')"
  BACKFILL_N="$(worker_count '[b]ackfill_from_raw.py')"
  LIVE_N="$(worker_count '[e]nrich_missing_live.py')"
  if background_ready && [ "$REBUILD_N" -eq 0 ] && [ "$FAST_N" -lt 4 ]; then
    AI_REMAIN="$(db_count "$AI_QUERY")"
    if [ "$AI_REMAIN" -gt 0 ]; then
      for WORKER in 0 1 2 3; do
        if ! pgrep -f "[g]enerate_ai_fast.py --worker $WORKER --workers 4" >/dev/null 2>&1; then
          nohup "$PYTHON" parser_v2/scripts/generate_ai_fast.py --worker "$WORKER" --workers 4 >> "logs/ai_w$WORKER.log" 2>&1 &
        fi
      done
      log_event "ai_rebuild_started remain=$AI_REMAIN"
    fi
  fi

  if background_ready && [ "$REBUILD_N" -eq 0 ]; then
    FULL_REBUILD_REMAIN="$(db_count "$AI_FULL_REBUILD_QUERY")"
    if [ "$FULL_REBUILD_REMAIN" -gt 0 ]; then
      for WORKER in 0 1 2 3; do
        nohup "$PYTHON" parser_v2/scripts/rebuild_ai_content.py --worker "$WORKER" --workers 4 --limit 1000 >> "logs/ai_rebuild_$WORKER.log" 2>&1 &
      done
      log_event "ai_full_rebuild_started remain=$FULL_REBUILD_REMAIN"
    fi
  fi

  if background_ready; then
    if [ "$BACKFILL_N" -eq 0 ]; then
      BACKFILL_REMAIN="$(db_count "SELECT count(*) FROM active_listings listing JOIN parser_v2_raw_listings raw ON raw.source=listing.source AND raw.external_id=listing.external_id LEFT JOIN listing_enrichment_attempts attempt ON attempt.listing_id=listing.id WHERE listing.status='active' AND listing.source IN ('olx','rieltor') AND raw.raw_html IS NOT NULL AND LENGTH(raw.raw_html)>500 AND (attempt.raw_checked_at IS NULL OR attempt.raw_checked_at < NOW() - INTERVAL '14 days') AND (listing.rooms IS NULL OR listing.area IS NULL OR listing.district IS NULL OR listing.district='' OR listing.street IS NULL OR listing.street='' OR listing.metro_station IS NULL OR listing.metro_station='' OR listing.photo_url IS NULL OR listing.photo_url='' OR listing.description IS NULL OR LENGTH(TRIM(COALESCE(listing.description,'')))<40 OR (listing.property_type='Квартира' AND (listing.floor IS NULL OR listing.floors_total IS NULL)) OR (listing.property_type='Будинок' AND listing.floors_total IS NULL))")"
      if [ "$BACKFILL_REMAIN" -gt 50 ]; then
        for WORKER in 0 1 2 3; do
          nohup "$PYTHON" parser_v2/scripts/backfill_from_raw.py --worker "$WORKER" --workers 4 --limit 500 >> "logs/raw_backfill_$WORKER.log" 2>&1 &
        done
        BACKFILL_N=1
        log_event "raw_backfill_started remain=$BACKFILL_REMAIN"
      fi
    fi
    if [ "$BACKFILL_N" -eq 0 ] && [ "$LIVE_N" -eq 0 ]; then
      LIVE_REMAIN="$(db_count "$LIVE_ENRICHMENT_QUERY")"
      if [ "$LIVE_REMAIN" -gt 0 ]; then
        for WORKER in 0 1 2 3; do
          nohup "$PYTHON" parser_v2/scripts/enrich_missing_live.py --source olx --worker "$WORKER" --workers 4 --limit 500 >> "logs/live_enrich_olx_$WORKER.log" 2>&1 &
        done
        nohup "$PYTHON" parser_v2/scripts/enrich_missing_live.py --source rieltor --worker 0 --workers 1 --limit 150 >> logs/live_enrich_rieltor.log 2>&1 &
        log_event "live_enrichment_started remain=$LIVE_REMAIN"
      fi
    fi

    QUALITY_MARKER="$PROJECT/.last_qfilter"
    if [ ! -f "$QUALITY_MARKER" ] || [ $(( $(date +%s) - $(stat -c %Y "$QUALITY_MARKER") )) -gt 21600 ]; then
      if "$PYTHON" parser_v2/scripts/quality_filter.py >> logs/qfilter.log 2>&1; then
        touch "$QUALITY_MARKER"
        log_event "quality_filter_complete"
      else
        log_event "quality_filter_failed"
      fi
    fi
  fi

  sleep 30
done
