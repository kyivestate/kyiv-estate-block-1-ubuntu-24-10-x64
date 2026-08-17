#!/usr/bin/env bash
set -euo pipefail

source_root="${1:?}"
target_root="${2:?}"
rsync -aHAX --numeric-ids --info=progress2 "$source_root/" "$target_root/"
