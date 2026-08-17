#!/bin/zsh
set -euo pipefail
project_dir="/Users/admin/Projects/real-estate-platform/telegram-bot"
cd "$project_dir"

# launchd invokes this script once a minute while a batch can legitimately run
# for several minutes.  Keep exactly one writer: concurrent workers can select
# the same source image before either one records its archive state.
lock_dir="/tmp/kyiv_estate_media_archive.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  if [ -r "$lock_dir/pid" ] && kill -0 "$(<"$lock_dir/pid")" 2>/dev/null; then
    exit 0
  fi
  rm -rf "$lock_dir"
  mkdir "$lock_dir"
fi
echo "$$" > "$lock_dir/pid"
trap 'rm -rf "$lock_dir"' EXIT INT TERM

# A stalled upstream image must never hold the single launchd job forever.
# media_archive.py checkpoints every completed image, so stopping a batch at
# eight minutes is safe: the next five-minute tick resumes only unfinished
# URLs.  This watchdog also keeps the Telegraph queue moving when a remote
# CDN stops responding despite its socket timeout.
"$project_dir/venv/bin/python" "$project_dir/telegraph_v3/media_archive.py" --limit 1000 --workers 12 &
worker_pid=$!
(
  sleep 480
  if kill -0 "$worker_pid" 2>/dev/null; then
    kill -TERM "$worker_pid" 2>/dev/null || true
    sleep 5
    kill -KILL "$worker_pid" 2>/dev/null || true
  fi
) &
watchdog_pid=$!

set +e
wait "$worker_pid"
worker_status=$?
set -e
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true
exit "$worker_status"
