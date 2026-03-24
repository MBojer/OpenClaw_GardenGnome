#!/usr/bin/env python3
"""
Geocode garden location via Open-Meteo, validate with a minimal forecast call, write config/garden.env.

Subcommands:
  search [WORDS ...] [--query STRING]  — list candidates (use --query for commas / one shell arg)
  smoke LAT LON          — bounds check + forecast API smoke test
  apply-search [WORDS ...] [--query STRING] --index N
  apply-coords LAT LON [--timezone TZ] — smoke, then set the three keys (timezone from Open-Meteo if omitted)

Shell tip: `search Aars Denmark` works (multiple words). For `skivum, 9240 nibe` use:
  search --query 'skivum, 9240 nibe, denmark'
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
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        u = getattr(e, "url", url)
        raise SystemExit(f"HTTP {e.code} from {u}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Network error ({url}): {e.reason}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON from API (truncated response?): {e}") from e


def resolve_place_query(cli_query: str | None, query_parts: list[str]) -> str:
    """Prefer --query string; else join positional words (so `search Aars Denmark` works)."""
    s = (cli_query or "").strip()
    if s:
        return s
    return " ".join(query_parts).strip()


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


def _place_tokens(query: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", query.strip()) if t]


def _variants_for_tokens(tokens: list[str]) -> list[str]:
    """Longest-first right-chop; skip a lone numeric token when other tokens exist (avoid ZIP-only false hits)."""
    out: list[str] = []
    for k in range(len(tokens), 0, -1):
        if k == 1 and len(tokens) > 1 and tokens[0].isdigit():
            continue
        s = " ".join(tokens[:k])
        if s and s not in out:
            out.append(s)
    return out


def _search_query_variants(query: str) -> list[str]:
    """Try full string, shorter tails, then same after stripping leading postcodes (e.g. 9240 Nibe -> Nibe)."""
    tokens = _place_tokens(query)
    if not tokens:
        return []
    seen: set[str] = set()
    variants: list[str] = []

    def extend(toks: list[str]) -> None:
        for s in _variants_for_tokens(toks):
            if s not in seen:
                seen.add(s)
                variants.append(s)

    extend(tokens)
    rest = tokens[:]
    while rest and rest[0].isdigit():
        rest = rest[1:]
    if rest and rest != tokens:
        extend(rest)
    return variants


def geocode_search_with_fallbacks(
    query: str,
    *,
    count: int,
    language: str,
) -> tuple[list[dict], str]:
    """
    Run geocode; if empty, retry shorter variants and optionally language=da for Denmark-related text.
    Returns (results, effective_query_string_used).
    """
    variants = _search_query_variants(query)
    langs_to_try = [language]
    if language != "da" and re.search(r"denmark|danmark|\bdk\b", query, re.I):
        langs_to_try.append("da")

    for lang in langs_to_try:
        for cand in variants:
            results = geocode_search(cand, count=count, language=lang)
            if results:
                if cand != query.strip() or lang != language:
                    print(
                        f"(geocode: using {cand!r}, language={lang} — full query returned no hits)",
                        file=sys.stderr,
                    )
                return results, cand
    return [], query.strip()


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


def fetch_forecast_smoke(lat: float, lon: float, base: str) -> dict:
    """Minimal forecast request; returns JSON on success; raises SystemExit on failure."""
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
    return data


def resolve_timezone(data: dict, preferred: str | None) -> str:
    tz = (preferred or "").strip() or (str(data.get("timezone") or "")).strip()
    if not tz:
        raise SystemExit(
            "Could not derive IANA timezone (Open-Meteo returned none); pass --timezone explicitly."
        )
    return tz


def apply_coords(
    env_path: Path,
    lat: float,
    lon: float,
    timezone_preferred: str | None,
    *,
    forecast_base: str,
) -> None:
    data = fetch_forecast_smoke(lat, lon, forecast_base)
    timezone = resolve_timezone(data, timezone_preferred)
    merge_env_key(env_path, "GARDEN_LAT", str(lat))
    merge_env_key(env_path, "GARDEN_LON", str(lon))
    merge_env_key(env_path, "GARDEN_TIMEZONE", timezone)
    print(f"Updated {env_path}: GARDEN_LAT, GARDEN_LON, GARDEN_TIMEZONE={timezone}")


def cmd_search(args: argparse.Namespace) -> int:
    q = resolve_place_query(args.query, args.query_parts)
    if not q:
        print(
            "geocode_garden search: pass a place name, e.g.\n"
            "  python3 scripts/geocode_garden.py search Aars Denmark\n"
            "  python3 scripts/geocode_garden.py search --query 'Skivum, 9240 Nibe, Denmark'\n"
            "Tip: try a shorter query (city + country) or --language da for Danish names.",
            file=sys.stderr,
        )
        return 2
    results, _used = geocode_search_with_fallbacks(q, count=args.count, language=args.language)
    if not results:
        print(
            f"No geocoding results for {q!r} (tried shorter variants) — "
            "try --query 'City, Country', fewer words, or --language da.",
            file=sys.stderr,
        )
        return 1
    print_candidates(results, as_json=args.json)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    lat, lon = parse_lat_lon(args.lat, args.lon)
    base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    data = fetch_forecast_smoke(lat, lon, base)
    print("OK: coordinates accepted and Open-Meteo returned daily data.")
    tzi = data.get("timezone")
    if tzi:
        print(f"Inferred timezone: {tzi}")
    return 0


def cmd_apply_search(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    env_path = Path(args.garden_env) if args.garden_env else root / "config" / "garden.env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    q = resolve_place_query(args.query, args.query_parts)
    if not q:
        print(
            "apply-search: pass the same place as search (words or --query '...') plus --index N.",
            file=sys.stderr,
        )
        return 2
    results, _used = geocode_search_with_fallbacks(q, count=args.count, language=args.language)
    if not results:
        print(f"No geocoding results for {q!r} (tried shorter variants).", file=sys.stderr)
        return 1
    idx = args.index
    if idx < 1 or idx > len(results):
        print(f"--index must be 1..{len(results)}", file=sys.stderr)
        return 1
    r = results[idx - 1]
    lat = float(r["latitude"])
    lon = float(r["longitude"])
    tz_hint = (r.get("timezone") or "").strip() or None

    forecast_base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    print(f"Applying: {candidate_label(r)}")
    apply_coords(env_path, lat, lon, tz_hint, forecast_base=forecast_base)
    return 0


def cmd_apply_coords(args: argparse.Namespace) -> int:
    root = workspace_root()
    load_garden_env(root)
    env_path = Path(args.garden_env) if args.garden_env else root / "config" / "garden.env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    lat, lon = parse_lat_lon(args.lat, args.lon)
    tz_pref = args.timezone.strip() if args.timezone else None

    forecast_base = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
    apply_coords(env_path, lat, lon, tz_pref, forecast_base=forecast_base)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Garden location geocode + validate + apply",
        epilog="Examples:\n"
        "  %(prog)s search Aars Denmark\n"
        "  %(prog)s search --query '9240 Nibe, Denmark' --language da\n"
        "  %(prog)s apply-search Aars Denmark --index 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser(
        "search",
        help="list geocoding candidates",
        epilog="Use several words without quotes (search Town Country) or --query 'full, address' for commas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_search.add_argument(
        "--query",
        "-q",
        default=None,
        metavar="STRING",
        help="full search string (recommended when the address has commas)",
    )
    p_search.add_argument(
        "query_parts",
        nargs="*",
        help="place words (e.g. Aars Denmark); joined with spaces",
    )
    p_search.add_argument("--count", type=int, default=8, help="max results (default 8)")
    p_search.add_argument("--language", default="en", help="ISO language for geocoder (try da for Denmark)")
    p_search.add_argument("--json", action="store_true", help="machine-readable output")
    p_search.set_defaults(func=cmd_search)

    p_smoke = sub.add_parser("smoke", help="validate lat/lon with Open-Meteo forecast")
    p_smoke.add_argument("lat")
    p_smoke.add_argument("lon")
    p_smoke.set_defaults(func=cmd_smoke)

    p_as = sub.add_parser("apply-search", help="apply geocoded candidate by 1-based index")
    p_as.add_argument(
        "--query",
        "-q",
        default=None,
        metavar="STRING",
        help="full search string (must match what you used for search)",
    )
    p_as.add_argument(
        "query_parts",
        nargs="*",
        help="same place words as search (e.g. Aars Denmark)",
    )
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
    p_ac.add_argument(
        "--timezone",
        default=None,
        help="IANA timezone; if omitted, use Open-Meteo forecast metadata for these coordinates",
    )
    p_ac.add_argument("--garden-env", help="path to garden.env (default: <repo>/config/garden.env)")
    p_ac.set_defaults(func=cmd_apply_coords)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
