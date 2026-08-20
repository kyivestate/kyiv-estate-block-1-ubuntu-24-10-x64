#!/usr/bin/env bash
set -euo pipefail

bundle="${1:?}"
project="${KYIV_ESTATE_HOME:-/opt/kyiv-estate-block-1}"
media_root="${MEDIA_ARCHIVE_ROOT:-/var/lib/kyiv-estate/media}"
test -r "$bundle/database/real_estate.dump"
test -r "$bundle/database/real_estate.dump.sha256"
test -r "$bundle/secrets/google-service-account.json"
test -r "$bundle/secrets/root.env"
(
  cd "$bundle/database"
  sha256sum --check real_estate.dump.sha256
)

install -d -m 0750 -o root -g kyivestate /etc/kyiv-estate
install -d -m 0750 -o kyivestate -g kyivestate "$media_root"
install -d -m 0750 -o kyivestate -g kyivestate "$project/telegraph_v3/data"
install -m 0640 -o root -g kyivestate "$bundle/secrets/google-service-account.json" /etc/kyiv-estate/google-service-account.json
install -m 0640 -o root -g kyivestate "$bundle/secrets/root.env" /etc/kyiv-estate/block-1.env
printf '\nKYIV_ESTATE_HOME=%s\nGOOGLE_CREDENTIALS_FILE=/etc/kyiv-estate/google-service-account.json\nMEDIA_ARCHIVE_ROOT=%s\n' "$project" "$media_root" >> /etc/kyiv-estate/block-1.env
test ! -f "$bundle/secrets/houses.env" || install -m 0640 -o root -g kyivestate "$bundle/secrets/houses.env" "$project/houses_v1/.env"
test ! -f "$bundle/secrets/cleaning.env" || install -m 0640 -o root -g kyivestate "$bundle/secrets/cleaning.env" "$project/cleaning/.env"
test ! -f "$bundle/secrets/commercial.sheets.json" || install -m 0640 -o root -g kyivestate "$bundle/secrets/commercial.sheets.json" "$project/commercial_v1/.sheets.json"
test ! -f "$bundle/secrets/telegraph-account.json" || install -m 0640 -o root -g kyivestate "$bundle/secrets/telegraph-account.json" "$project/telegraph_v3/data/telegraph-account.json"
set -a
source /etc/kyiv-estate/block-1.env
set +a
if [[ -z "${PG_PASSWORD:-}" ]]; then
  export PG_PASSWORD="$(openssl rand -hex 32)"
  printf 'PG_PASSWORD=%s\n' "$PG_PASSWORD" >> /etc/kyiv-estate/block-1.env
fi
if [[ "${PG_HOST:-127.0.0.1}" == "127.0.0.1" || "${PG_HOST:-}" == "localhost" ]]; then
  [[ "${PG_USER:?}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
  password_sql=${PG_PASSWORD//\'/\'\'}
  systemctl enable --now postgresql
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE \"$PG_USER\" LOGIN CREATEDB PASSWORD '$password_sql';" 2>/dev/null || \
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$PG_USER\" LOGIN CREATEDB PASSWORD '$password_sql' CREATEDB;"
fi
"$project/deploy/ubuntu-24.10-x64/restore-state.sh" "$bundle/database/real_estate.dump"
test ! -d "$bundle/media" || rsync -aHAX --delete "$bundle/media/" "$media_root/"
chown -R kyivestate:kyivestate "$media_root"
systemctl restart kyiv-estate-block1.service kyiv-estate-guard.service kyiv-estate-media.service
