#!/usr/bin/env bash
set -euo pipefail

dump_file="${1:?}"
test -r "$dump_file"
dropdb --if-exists -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "${PG_USER:?}" "${PG_DBNAME:?}"
createdb -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "${PG_USER:?}" "${PG_DBNAME:?}"
pg_restore --no-owner --no-privileges -h "${PG_HOST:-127.0.0.1}" -p "${PG_PORT:-5432}" -U "${PG_USER:?}" -d "${PG_DBNAME:?}" "$dump_file"
