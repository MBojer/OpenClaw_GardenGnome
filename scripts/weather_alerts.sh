#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

STATEF="$ROOT/.openclaw/gardengnome-state.json"
READY="$(python3 - "$STATEF" <<'PY'
import json, sys
path = sys.argv[1]
def is_non_null(v):
    return v is not None and v != "" and v != "null"
ready = False
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    onboard = data.get("onboarding") or {}
    weather = data.get("weather") or {}
    loc = onboard.get("locationDoneAt", None)
    hist = weather.get("historicalBackfillAt", None)
    ready = is_non_null(loc) and is_non_null(hist)
except Exception:
    ready = False
print("1" if ready else "0")
PY
)"
if [[ "$READY" != "1" ]]; then
  echo "Skipping weather_alerts: onboarding.locationDoneAt and weather.historicalBackfillAt must both be set in .openclaw/gardengnome-state.json"
  exit 0
fi

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
