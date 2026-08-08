#!/bin/bash
# Loops the same "run.py --execute -> dashboard.py" cycle automate.sh does locally via
# launchd, but from inside the container so `restart: unless-stopped` can bring it back
# after a crash or VPS reboot without any host-level scheduler.
set -u
cd "$(dirname "$0")"

INTERVAL="${CYCLE_INTERVAL_SECONDS:-900}"

trap 'echo "Received stop signal, exiting."; exit 0' SIGTERM SIGINT

while true; do
  echo "===== $(date -u +"%Y-%m-%dT%H:%M:%SZ") ====="
  python3 run.py --execute
  python3 dashboard.py
  sleep "$INTERVAL" &
  wait $!
done
