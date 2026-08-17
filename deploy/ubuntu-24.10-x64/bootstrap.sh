#!/usr/bin/env bash
set -euo pipefail

project="${1:-/opt/kyiv-estate-block-1}"
user="${2:-kyivestate}"
apt-get update
apt-get install -y python3 python3-venv python3-dev build-essential libpq-dev postgresql-client rsync git curl
id "$user" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$user"
install -d -o "$user" -g "$user" /var/lib/kyiv-estate /var/log/kyiv-estate /etc/kyiv-estate "$project/logs" "$project/backups/production"
python3 -m venv "$project/venv"
"$project/venv/bin/pip" install --upgrade pip
"$project/venv/bin/pip" install -r "$project/requirements-production.txt"
install -m 0640 -o root -g "$user" "$project/deploy/ubuntu-24.10-x64/kyiv-estate.env.example" /etc/kyiv-estate/block-1.env
install -m 0644 "$project/deploy/ubuntu-24.10-x64/systemd/kyiv-estate-block1.service" /etc/systemd/system/kyiv-estate-block1.service
install -m 0644 "$project/deploy/ubuntu-24.10-x64/systemd/kyiv-estate-guard.service" /etc/systemd/system/kyiv-estate-guard.service
install -m 0644 "$project/deploy/ubuntu-24.10-x64/systemd/kyiv-estate-media.service" /etc/systemd/system/kyiv-estate-media.service
systemctl daemon-reload
systemctl enable kyiv-estate-block1.service kyiv-estate-guard.service kyiv-estate-media.service
