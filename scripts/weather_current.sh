#!/usr/bin/env bash
# Fetch current + hourly + daily forecast from Open-Meteo; load garden.* tables; refresh alerts.
# Intended: every 30 minutes (systemd timer). Rate limit: stay at ≥15 min between calls.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENVF="$ROOT/config/garden.env"
if [[ ! -f "$ENVF" ]]; then
  echo "Missing $ENVF (copy config/garden.env.template)" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
source "$ENVF"
set +a

LOG="${WEATHER_CURRENT_LOG:-$ROOT/logs/weather_current.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

echo "=== $(date -Iseconds) weather_current start ==="

BASE="${OPEN_METEO_URL:-https://api.open-meteo.com}"
TMP="$(mktemp)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

curl -sS -f -o "$TMP" -G "${BASE}/v1/forecast" \
  --data-urlencode "latitude=${GARDEN_LAT}" \
  --data-urlencode "longitude=${GARDEN_LON}" \
  --data-urlencode "current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m,dew_point_2m,uv_index,visibility" \
  --data-urlencode "hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,rain,snowfall,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,dew_point_2m,uv_index" \
  --data-urlencode "daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max,precipitation_sum,rain_sum,snowfall_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max" \
  --data-urlencode "forecast_days=7" \
  --data-urlencode "hourly_forecast_days=2" \
  --data-urlencode "timezone=auto" \
  --data-urlencode "wind_speed_unit=ms"

{
  echo "BEGIN;"
  echo "TRUNCATE garden.weather_forecast_hourly RESTART IDENTITY;"
  python3 "$ROOT/scripts/weather_parse.py" --file "$TMP" --mode hourly
  echo "TRUNCATE garden.weather_forecast_daily RESTART IDENTITY;"
  python3 "$ROOT/scripts/weather_parse.py" --file "$TMP" --mode daily
  python3 "$ROOT/scripts/weather_parse.py" --file "$TMP" --mode current
  echo "COMMIT;"
} | psql "${GARDEN_DB_URL}" -v ON_ERROR_STOP=1 -f -

bash "$ROOT/scripts/weather_alerts.sh"
echo "=== $(date -Iseconds) weather_current done ==="
