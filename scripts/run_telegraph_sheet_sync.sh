#!/usr/bin/env bash
set -euo pipefail

PROJECT="${KYIV_ESTATE_HOME:?}"
cd "$PROJECT"
exec "$PROJECT/venv/bin/python" telegraph_v3/sync_to_sheets.py
