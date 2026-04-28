#!/usr/bin/env bash
# Wrapper: cd into repo, source .env, run a script with the venv python.
# Use from cron: /opt/tourscale/reports/scripts/run.sh ga4_weekly.py
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . .env
set +a
exec .venv/bin/python "$@"
