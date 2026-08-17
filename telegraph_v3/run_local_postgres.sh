#!/bin/zsh
# Run the local project database without Postgres.app's interactive-only
# permission-dialog preload.  Access remains protected by SCRAM credentials
# in pg_hba.conf; this makes launchd services safe to run unattended.
set -euo pipefail
exec /Applications/Postgres.app/Contents/Versions/18/bin/postgres \
  -D "/Users/admin/Library/Application Support/Postgres/var-18" \
  -p 5432 \
  -c "shared_preload_libraries="
