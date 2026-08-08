#!/bin/bash
# Loops the same "run.py --execute -> dashboard.py" cycle automate.sh does locally via
# launchd, but from inside the container so `restart: unless-stopped` can bring it back
# after a crash or VPS reboot without any host-level scheduler.
#
# If the container is started with an explicit command (e.g. docker-compose's
# `command: ["python3", "dashboard_server.py"]` for the dashboard service), run that
# instead of the trading loop — otherwise it's silently ignored since ENTRYPOINT always
# runs and CMD/`command:` just becomes its arguments.
set -u
cd "$(dirname "$0")"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

INTERVAL="${CYCLE_INTERVAL_SECONDS:-900}"

trap 'echo "Received stop signal, exiting."; exit 0' SIGTERM SIGINT

while true; do
  echo "===== $(date -u +"%Y-%m-%dT%H:%M:%SZ") ====="
  python3 run.py --execute
  python3 dashboard.py
  sleep "$INTERVAL" &
  wait $!
done
