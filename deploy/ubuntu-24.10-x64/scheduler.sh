#!/usr/bin/env bash
set -euo pipefail

project="${KYIV_ESTATE_HOME:?}"
runner="$project/deploy/ubuntu-24.10-x64/run-task.sh"
state_dir=/var/lib/kyiv-estate/scheduler
mkdir -p "$state_dir"

run_due() {
  local task="$1" interval="$2" now last
  now="$(date +%s)"
  last=0
  test -f "$state_dir/$task" && last="$(cat "$state_dir/$task")"
  if (( now - last < interval )); then return; fi
  printf '%s' "$now" > "$state_dir/$task"
  flock -n "/run/kyiv-estate-$task.lock" "$runner" "$task" || true
}

while true; do
  run_due apartments 1800 &
  run_due houses 1800 &
  run_due commercial 1800 &
  run_due commercial-sheets 900 &
  run_due reconcile 300 &
  run_due empty-rows 600 &
  run_due statuses 1800 &
  run_due telegraph-sheets 300 &
  run_due media-archive 300 &
  run_due backup 7200 &
  wait
  sleep 30
done
