#!/usr/bin/env python3
"""
Geocode garden location via Open-Meteo, validate with a minimal forecast call, write config/garden.env.

Subcommands:
  search QUERY           — list numbered candidates (exit 1 if none)
  smoke LAT LON          — bounds check + forecast API smoke test
  apply-search QUERY --index N   — pick candidate, smoke, then set GARDEN_LAT/LON/TIMEZONE
  apply-coords LAT LON --timezone TZ — smoke, then set the three keys
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


UA = "GardenGnome-geocode/1.0"


def merge_env_key(path: Path, key: str, val: str) -> None:
    """Set or replace KEY=\"value\" in a dotenv file (same rules as install/merge_env_key.py)."""
    esc = val.replace("\\", "\\\\").replace('"', '\\"')
    line = f'{key}="{esc}"\n'
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pat = re.compile("^" + re.escape(key) + r"=.*$", re.MULTILINE)
    if pat.search(text):
        text = pat.sub(line.rstrip("\n"), text, count=1)
        if not text.endswith("\n"):
            text += "\n"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    path.write_text(text, encoding="utf-8")


def load_garden_env(root: Path) -> None:
    env_path = root / "config" / "garden.env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode_search(
    query: str,
    *,
    count: int,
    language: str,
    base: str = "https://geocoding-api.open-meteo.com",
) -> list[dict]:
    q = urllib.parse.urlencode(
        {
            "name": query,
            "count": str(count),
            "language": language,
            "format": "json",
        }
    )
    url = f"{base.rstrip('/')}/v1/search?{q}"
    data = fetch_json(url)
    return list(data.get("results") or [])


def candidate_label(r: dict) -> str:
    parts = [r.get("name") or "?"]
    a1 = r.get("admin1")
    if a1:
        parts.append(str(a1))
    c = r.get("country")
    if c:
        parts.append(str(c))
    return ", ".join(parts)


def print_candidates(results: list[dict], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"results": results}, indent=2))
        return
    for i, r in enumerate(results, start=1):
        lat, lon = r.get("latitude"), r.get("longitude")
        tz = r.get("timezone") or ""
        print(f"{i}. {candidate_label(r)}")
        print(f"   lat={lat} lon={lon} timezone={tz}")


def parse_lat_lon(a: str, b: str) -> tuple[float, float]:
    try:
        lat = float(a)
        lon = float(b)
    except ValueError as e:
        raise SystemExit(f"invalid latitude/longitude: {e}") from e
    if not -90.0 <= lat <= 90.0:
        raise SystemExit(f"latitude out of range [-90, 90]: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise SystemExit(f"longitude out of range [-180, 180]: {lon}")
    return lat, lon


def smoke_forecast(lat: float, lon: float, base: str) -> None:
    """Minimal forecast request; raises SystemExit on failure."""
    q = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max",
            "forecast_days": "1",
            "timezone": "auto",
        }
    )
    url = f"{base.rstrip('/')}/v1/forecast?{q}"
    try:
        data = fetch_json(url)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"forecast HTTP {e.code}: Open-Meteo rejected this location") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"forecast network error: {e}") from e
    daily = data.get("daily")
    if not isinstance(daily, dict):
        raise SystemExit("forecast response missing daily series (invalid location or API error)")
    times = daily.get("time")
    if not isinstance(times, list) or len(times) < 1:
        raise SystemExit("forecast daily.time empty — location may be invalid for weather data")


def apply_coords(
    env_path: Path,
    lat: float,
    lon: float,
    timezone: str,
    *,
    forecast_base: str,
) -> None:
    smoke_forecast(lat, lon, forecast_base)
    merge_env_key(env_path, "GARDEN_LAT", str(lat))
    merge_env_key(env_path, "GARDEN_LON", str(lon))
    merge_env_key(env_path, "GARDEN_TIMEZONE", timezone)
    print(f"Updated {env_path}: GARDEN_LAT, GARDEN_LON, GARDEN_TIMEZONE")


def cmd_search(args: argparse.Namespace) -> int:
    results = geocode_search(args.query, count=args.count, language=args.language)
    if not results:
        print("No geocoding results — refine the query (add country, fix spelling).", file=sys.stderr)
        return 1
    print_candidates(results, as_json=args.json)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    lat, lon = parse_lat_lon(args.lat, args.lon)
    base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    smoke_forecast(lat, lon, base)
    print("OK: coordinates accepted and Open-Meteo returned daily data.")
    return 0


def cmd_apply_search(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    env_path = Path(args.garden_env) if args.garden_env else root / "config" / "garden.env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    results = geocode_search(args.query, count=args.count, language=args.language)
    if not results:
        print("No geocoding results.", file=sys.stderr)
        return 1
    idx = args.index
    if idx < 1 or idx > len(results):
        print(f"--index must be 1..{len(results)}", file=sys.stderr)
        return 1
    r = results[idx - 1]
    lat = float(r["latitude"])
    lon = float(r["longitude"])
    tz = r.get("timezone") or ""
    if not tz:
        print("Geocoder returned no timezone; use apply-coords with --timezone.", file=sys.stderr)
        return 1

    forecast_base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    print(f"Applying: {candidate_label(r)}")
    apply_coords(env_path, lat, lon, tz, forecast_base=forecast_base)
    return 0


def cmd_apply_coords(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    env_path = Path(args.garden_env) if args.garden_env else root / "config" / "garden.env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    lat, lon = parse_lat_lon(args.lat, args.lon)
    tz = args.timezone.strip()
    if not tz:
        print("--timezone is required for apply-coords", file=sys.stderr)
        return 1

    forecast_base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    apply_coords(env_path, lat, lon, tz, forecast_base=forecast_base)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Garden location geocode + validate + apply")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="list geocoding candidates")
    p_search.add_argument("query", help="city, address, or place name")
    p_search.add_argument("--count", type=int, default=8, help="max results (default 8)")
    p_search.add_argument("--language", default="en")
    p_search.add_argument("--json", action="store_true", help="machine-readable output")
    p_search.set_defaults(func=cmd_search)

    p_smoke = sub.add_parser("smoke", help="validate lat/lon with Open-Meteo forecast")
    p_smoke.add_argument("lat")
    p_smoke.add_argument("lon")
    p_smoke.set_defaults(func=cmd_smoke)

    p_as = sub.add_parser("apply-search", help="apply geocoded candidate by 1-based index")
    p_as.add_argument("query")
    p_as.add_argument("--index", type=int, required=True)
    p_as.add_argument("--count", type=int, default=10, help="fetch up to N matches before --index")
    p_as.add_argument("--language", default="en")
    p_as.add_argument(
        "--garden-env",
        help="path to garden.env (default: <repo>/config/garden.env)",
    )
    p_as.set_defaults(func=cmd_apply_search)

    p_ac = sub.add_parser("apply-coords", help="apply explicit coordinates after smoke test")
    p_ac.add_argument("lat")
    p_ac.add_argument("lon")
    p_ac.add_argument("--timezone", required=True)
    p_ac.add_argument("--garden-env", help="path to garden.env (default: <repo>/config/garden.env)")
    p_ac.set_defaults(func=cmd_apply_coords)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
