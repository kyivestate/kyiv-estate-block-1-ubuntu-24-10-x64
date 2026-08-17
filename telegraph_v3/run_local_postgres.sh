set -euo pipefail
exec /Applications/Postgres.app/Contents/Versions/18/bin/postgres \
  -D "/Users/admin/Library/Application Support/Postgres/var-18" \
  -p 5432 \
  -c "shared_preload_libraries="
