#!/usr/bin/env bash
set -euo pipefail

bundle="${1:?}"
project="${KYIV_ESTATE_HOME:-/opt/kyiv-estate-block-1}"
media_root="${MEDIA_ARCHIVE_ROOT:-/var/lib/kyiv-estate/media}"
test -r "$bundle/database/real_estate.dump"
test -r "$bundle/secrets/google-service-account.json"
test -r "$bundle/secrets/root.env"

install -d -m 0750 /etc/kyiv-estate
install -d -m 0750 "$media_root"
install -m 0640 "$bundle/secrets/google-service-account.json" /etc/kyiv-estate/google-service-account.json
install -m 0640 "$bundle/secrets/root.env" /etc/kyiv-estate/block-1.env
printf '\nKYIV_ESTATE_HOME=%s\nGOOGLE_CREDENTIALS_FILE=/etc/kyiv-estate/google-service-account.json\nMEDIA_ARCHIVE_ROOT=%s\n' "$project" "$media_root" >> /etc/kyiv-estate/block-1.env
test ! -f "$bundle/secrets/houses.env" || install -m 0640 "$bundle/secrets/houses.env" "$project/houses_v1/.env"
test ! -f "$bundle/secrets/cleaning.env" || install -m 0640 "$bundle/secrets/cleaning.env" "$project/cleaning/.env"
test ! -f "$bundle/secrets/commercial.sheets.json" || install -m 0640 "$bundle/secrets/commercial.sheets.json" "$project/commercial_v1/.sheets.json"
test ! -f "$bundle/secrets/telegraph-account.json" || install -m 0640 "$bundle/secrets/telegraph-account.json" "$project/telegraph_v3/data/telegraph-account.json"
set -a
source /etc/kyiv-estate/block-1.env
set +a
"$project/deploy/ubuntu-24.10-x64/restore-state.sh" "$bundle/database/real_estate.dump"
test ! -d "$bundle/media" || rsync -aHAX --delete "$bundle/media/" "$media_root/"
systemctl restart kyiv-estate-block1.service kyiv-estate-guard.service kyiv-estate-media.service
