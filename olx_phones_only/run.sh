#!/usr/bin/env bash
set -euo pipefail
cd ${KYIV_ESTATE_HOME:?}/olx_phones_only

source ../venv/bin/activate 2>/dev/null || python3 -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt

psql -d real_estate -f sql/01_create_schema.sql

python scripts/import_urls.py
python scripts/fetch_phones.py
psql -d real_estate -f sql/report.sql
