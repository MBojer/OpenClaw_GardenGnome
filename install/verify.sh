#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

echo "Running scaffold verification..."

missing=0
for required in \
  "README.md" "install.sh" ".env.example" "install/setup_env.sh" "install/setup_db.sh" \
  "install/merge_env_key.py" "install/setup_cron.py" "install/requirements-constrained-llm.txt" \
  "install/requirements-weather.txt" \
  "db/postgres/001_schema_placeholder.sql" "db/postgres/002_openclaw_constrained_llm.sql" \
  "db/postgres/004_garden_weather.sql" \
  "db/postgres/seeds/003_example_openclaw_context.sql" \
  "config/garden.env.template" "config/gardengnome-state.example.json" \
  "scripts/constrained_llm_pipeline.py" \
  "scripts/geocode_garden.py" \
  "scripts/weather_parse.py" "scripts/weather_historical_backfill.py" "scripts/weather_alerts.py" \
  "scripts/weather_current.sh" "scripts/weather_archive.sh" "scripts/weather_alerts.sh" \
  "scripts/setup_cron.sh" "scripts/daily_briefing.sh" "scripts/sql/daily_briefing_weather.sql" \
  "install/systemd/user/gardengnome-weather-current.service" \
  "install/systemd/user/gardengnome-weather-current.timer" \
  "install/systemd/user/gardengnome-weather-archive.service" \
  "install/systemd/user/gardengnome-weather-archive.timer" \
  "install/systemd/user/gardengnome-weather-alerts.service" \
  "install/systemd/user/gardengnome-weather-alerts.timer" \
  "ref/CLIMATE.md"; do
  if [[ ! -f "$required" ]]; then
    echo "ERROR: Missing required file: $required"
    missing=1
  fi
done

for cmd in python3 node jq git curl crontab; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "WARN: Command not found: $cmd"
  fi
done

if ! command -v openclaw >/dev/null 2>&1; then
  echo "WARN: openclaw CLI not found (required for agent registration)."
fi

if [[ $missing -ne 0 ]]; then
  exit 1
fi

echo "Scaffold verification finished."
