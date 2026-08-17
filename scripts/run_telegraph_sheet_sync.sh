#!/bin/bash
set -euo pipefail

PROJECT="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$PROJECT"
# Block 3 is the single publication ledger for apartments, houses and
# commercial listings.  The older Block 2 synchronizer does not know about
# houses and would leave valid new pages out of their Active sheet.
exec "$PROJECT/venv/bin/python" telegraph_v3/sync_to_sheets.py
