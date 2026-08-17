#!/usr/bin/env bash
set -euo pipefail
ROOT="${KYIV_ESTATE_HOME:?}"
cd "$ROOT"
exec "$ROOT/venv/bin/python" -m manual_ingest
