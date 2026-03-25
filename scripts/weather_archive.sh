#!/usr/bin/env bash
# Daily: fill garden.weather_log gaps up to (today - 6) via archive API (~5 day lag).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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
  echo "Skipping weather_archive: onboarding.locationDoneAt and weather.historicalBackfillAt must both be set in .openclaw/gardengnome-state.json"
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

LOG="${WEATHER_ARCHIVE_LOG:-$ROOT/logs/weather_archive.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

echo "=== $(date -Iseconds 2>/dev/null || date) weather_archive start ==="

RANGE=()
while IFS= read -r line; do
  [[ -n "$line" ]] && RANGE+=("$line")
done < <(python3 - <<'PY'
import os
from datetime import date, timedelta
from subprocess import check_output

db = os.environ.get("GARDEN_DB_URL", "")
if not db:
    raise SystemExit("GARDEN_DB_URL missing")
out = check_output(
    ["psql", db, "-tAqc", "SELECT COALESCE(MAX(log_date)::text, '') FROM garden.weather_log;"],
    text=True,
).strip()
end = date.today() - timedelta(days=6)
if not out:
    start = date(2016, 1, 1)
else:
    start = date.fromisoformat(out) + timedelta(days=1)
print(start.isoformat())
print(end.isoformat())
PY
)

START="${RANGE[0]:-}"
END="${RANGE[1]:-}"
if [[ -z "$START" || -z "$END" ]]; then
  echo "Could not compute archive range"
  exit 1
fi
if [[ "$START" > "$END" ]]; then
  echo "weather_log up to date (start $START > end $END)"
  exit 0
fi

BASE="${OPEN_METEO_ARCHIVE_URL:-https://archive-api.open-meteo.com}"
TMP="$(mktemp)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

curl -sS -f -o "$TMP" -G "${BASE}/v1/archive" \
  --data-urlencode "latitude=${GARDEN_LAT}" \
  --data-urlencode "longitude=${GARDEN_LON}" \
  --data-urlencode "start_date=${START}" \
  --data-urlencode "end_date=${END}" \
  --data-urlencode "daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,rain_sum,snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,relative_humidity_2m_mean,dew_point_2m_mean,pressure_msl_mean,sunshine_duration,uv_index_max,et0_fao_evapotranspiration,weather_code" \
  --data-urlencode "wind_speed_unit=ms" \
  --data-urlencode "timezone=auto"

python3 "$ROOT/scripts/weather_parse.py" --file "$TMP" --mode archive | psql "${GARDEN_DB_URL}" -v ON_ERROR_STOP=1 -f -

echo "=== $(date -Iseconds 2>/dev/null || date) weather_archive done ==="
