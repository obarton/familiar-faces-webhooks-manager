#!/usr/bin/env bash
#
# Run the whole app locally: the Django web server AND the competitor-refresh
# background worker, together, in one terminal. Ctrl-C stops both.
#
# Usage:
#   ./run.sh                 # server on :8000, worker every 900s (15 min)
#   ./run.sh 8080            # custom port
#   ./run.sh 8080 300        # custom port + worker interval (seconds)
#
# (Production runs the server via gunicorn and the worker as a separate process;
#  this script is for local development.)
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8000}"
INTERVAL="${2:-900}"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "ERROR: .venv not found. Run ./setup.sh first." >&2
  exit 1
fi

pids=()
_cleaned=""
cleanup() {
  [ -n "$_cleaned" ] && return
  _cleaned=1
  echo ""
  echo "Shutting down…"
  for pid in "${pids[@]}"; do
    # Kill child processes too — runserver's auto-reloader forks a worker that
    # would otherwise be orphaned and keep holding the port.
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> Background refresh worker (every ${INTERVAL}s)"
"$PY" manage.py refresh_competitors --loop "$INTERVAL" &
pids+=($!)

echo "==> Web server at http://127.0.0.1:${PORT}/"
"$PY" manage.py runserver "$PORT" &
pids+=($!)

echo ""
echo "Both running. Press Ctrl-C to stop."

# Portable supervisor (works on macOS's bash 3.2, which lacks `wait -n`):
# if either process exits, tear the other down too.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A process exited — stopping the other."
      exit 1
    fi
  done
  sleep 2
done
