#!/usr/bin/env bash
set -euo pipefail
exec postgres -D "${PGDATA:?}" \
  -p 5432 \
  -c "shared_preload_libraries="
