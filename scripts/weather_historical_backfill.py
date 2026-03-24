#!/usr/bin/env python3
"""
One-time (or rerun-safe) historical weather backfill via Open-Meteo archive API.
Fetches 2016-01-01 through (today - 6 days) in yearly chunks; INSERT … ON CONFLICT is idempotent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path


def load_garden_env(root: Path) -> None:
    env_path = root / "config" / "garden.env"
    if not env_path.is_file():
        print(f"Missing {env_path}; copy from config/garden.env.template", file=sys.stderr)
        sys.exit(1)
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def archive_url(lat: float, lon: float, start: date, end: date, base: str) -> str:
    daily = (
        "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
        "precipitation_sum,rain_sum,snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,"
        "relative_humidity_2m_mean,dew_point_2m_mean,pressure_msl_mean,sunshine_duration,"
        "uv_index_max,et0_fao_evapotranspiration,weather_code"
    )
    q = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": daily,
            "wind_speed_unit": "ms",
            "timezone": "auto",
        }
    )
    return f"{base.rstrip('/')}/v1/archive?{q}"


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "GardenGnome-weather/2"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    load_garden_env(root)
    lat = float(os.environ["GARDEN_LAT"])
    lon = float(os.environ["GARDEN_LON"])
    base = os.environ.get("OPEN_METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com")
    end = date.today() - timedelta(days=6)
    first = date(2016, 1, 1)
    if first > end:
        print("Nothing to backfill (end before start)")
        return 0

    parse_py = root / "scripts" / "weather_parse.py"
    db_url = os.environ.get("GARDEN_DB_URL")
    if not db_url:
        print("GARDEN_DB_URL required", file=sys.stderr)
        return 1

    tmp_dir = root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for year in range(2016, end.year + 1):
        chunk_start = max(date(year, 1, 1), first)
        chunk_end = min(date(year, 12, 31), end)
        if chunk_start > chunk_end:
            continue
        url = archive_url(lat, lon, chunk_start, chunk_end, base)
        print(f"Fetching {chunk_start} .. {chunk_end} …", flush=True)
        try:
            data = fetch_json(url)
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
            continue
        tmp = tmp_dir / f"weather_archive_{year}.json"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(parse_py), "--mode", "archive", "--file", str(tmp)],
            capture_output=True,
            text=True,
            check=True,
        )
        sql_text = proc.stdout
        if not sql_text.strip():
            print(f"  no rows for {year}", flush=True)
            continue
        sub = subprocess.run(
            ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-f", "-"],
            input=sql_text,
            text=True,
        )
        if sub.returncode != 0:
            return sub.returncode
        print(f"  applied {year}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
