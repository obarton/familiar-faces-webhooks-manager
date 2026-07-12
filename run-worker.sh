#!/usr/bin/env bash
#
# Run the competitor-refresh background worker.
#
# Crawls competitors that were queued from the UI or have gone stale, every
# INTERVAL seconds. Leave this running in a terminal (local) or as a worker
# process (production). For a real OS/PaaS cron, run the one-shot form instead:
#   .venv/bin/python manage.py refresh_competitors
#
# Usage:
#   ./run-worker.sh            # refresh every 900s (15 min)
#   ./run-worker.sh 300        # custom interval in seconds
#
set -euo pipefail
cd "$(dirname "$0")"

INTERVAL="${1:-900}"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "ERROR: .venv not found. Run ./setup.sh first." >&2
  exit 1
fi

exec "$PY" manage.py refresh_competitors --loop "$INTERVAL"
