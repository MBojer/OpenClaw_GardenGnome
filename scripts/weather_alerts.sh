#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="$ROOT/config/garden.env"
if [[ ! -f "$ENVF" ]]; then
  echo "Missing $ENVF" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
source "$ENVF"
set +a

LOG="${WEATHER_ALERTS_LOG:-$ROOT/logs/weather_alerts.log}"
mkdir -p "$(dirname "$LOG")"
if [[ "${WEATHER_ALERTS_LOG_APPEND:-1}" == "1" ]]; then
  exec >>"$LOG" 2>&1
fi

python3 "$ROOT/scripts/weather_alerts.py"
