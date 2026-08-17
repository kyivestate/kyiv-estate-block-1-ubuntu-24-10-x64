#!/usr/bin/env bash
set -euo pipefail

project="${KYIV_ESTATE_HOME:?}"
python="$project/venv/bin/python"
cd "$project"

case "${1:?}" in
  apartments) exec "$project/scripts/run_incremental_parser.sh" ;;
  houses) exec "$project/houses_v1/run_incremental_houses.sh" ;;
  commercial) exec "$project/commercial_v1/run_incremental_commercial.sh" ;;
  commercial-sheets) exec "$project/commercial_v1/run_sheets_sync.sh" ;;
  reconcile) exec "$project/scripts/run_active_sheet_id_reconcile.sh" ;;
  empty-rows) exec "$project/scripts/run_remove_empty_active_sheet_rows.sh" ;;
  statuses) exec "$project/scripts/run_status_checks.sh" ;;
  backup) exec "$project/scripts/run_production_backup.sh" ;;
  telegraph-sheets) exec "$project/telegraph_v3/run_sheet_sync.sh" ;;
  media-archive) exec "$project/telegraph_v3/run_media_archive.sh" ;;
  *) exit 64 ;;
esac
