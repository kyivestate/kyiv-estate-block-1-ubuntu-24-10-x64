#!/bin/bash
set -euo pipefail

cd /Users/admin/Projects/real-estate-platform/telegram-bot

if [ ! -d venv ]; then
  python3 -m venv venv
fi

source venv/bin/activate
pip install -r olx_phone_coverage/requirements_olx_phone.txt

psql -d real_estate -f olx_phone_coverage/sql/001_create_olx_phone_coverage.sql

python -m olx_phone_coverage.import_sheet_urls
python -m olx_phone_coverage.fetch_phones
psql -d real_estate -f olx_phone_coverage/report.sql
