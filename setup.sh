#!/usr/bin/env bash
#
# Development environment setup for the Familiar Faces marketing platform.
#
# Idempotent: safe to re-run. It will
#   1. create a Python virtual environment in .venv (if missing)
#   2. install/upgrade pip and the packages in requirements.txt
#   3. apply database migrations
#   4. optionally bootstrap a superuser (via `manage.py ensure_admin`)
#
# Usage:
#   ./setup.sh              # set up venv, install deps, run migrations
#   ./setup.sh --admin      # also create/ensure the superuser from .env
#
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
PY_BIN="$VENV_DIR/bin/python"

# --- 1. Pick a Python interpreter ------------------------------------------
# Prefer 3.11 (best wheel compatibility for this project), then any python3.
pick_python() {
  for cand in python3.11 python3.12 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$PY_BIN" ]; then
  BASE_PYTHON="$(pick_python)" || {
    echo "ERROR: no python3 interpreter found on PATH." >&2
    exit 1
  }
  echo "==> Creating virtual environment in $VENV_DIR (using $BASE_PYTHON)"
  "$BASE_PYTHON" -m venv "$VENV_DIR"
else
  echo "==> Reusing existing virtual environment in $VENV_DIR"
fi

# --- 2. Install dependencies -----------------------------------------------
echo "==> Upgrading pip"
"$PY_BIN" -m pip install --quiet --upgrade pip

echo "==> Installing requirements"
"$PY_BIN" -m pip install --quiet -r requirements.txt

# --- 3. Environment file ----------------------------------------------------
if [ ! -f ".env" ]; then
  echo "==> WARNING: no .env file found. Copy/create one before running the app."
  echo "    (FIRECRAWL_API_KEY, GOOGLE_*, MAILCHIMP_*, SECRET_KEY, etc.)"
fi

# --- 4. Migrations ----------------------------------------------------------
echo "==> Applying database migrations"
"$PY_BIN" manage.py migrate

# --- 5. Optional superuser --------------------------------------------------
if [ "${1:-}" = "--admin" ]; then
  echo "==> Ensuring superuser (from DJANGO_SUPERUSER_* in .env)"
  "$PY_BIN" manage.py ensure_admin
fi

echo ""
echo "Setup complete."
echo "  Activate the venv:   source $VENV_DIR/bin/activate"
echo "  Run the dev server:  $PY_BIN manage.py runserver"
echo "  Track competitors:   $PY_BIN manage.py refresh_competitors"
