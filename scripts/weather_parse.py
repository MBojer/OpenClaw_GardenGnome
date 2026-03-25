#!/usr/bin/env python3
"""
Parse Open-Meteo JSON and emit SQL for weather.* weather tables.
Usage: weather_parse.py --mode current|hourly|daily|archive [--file path]
JSON on stdin if --file omitted. Threshold env vars optional (see config/garden.env.template).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# WMO weather_code (0-99) → short description for briefings
WMO_WEATHER_DESCRIPTION: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return WMO_WEATHER_DESCRIPTION.get(int(code), f"Code {code}")


def _f(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def sql_escape(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def sql_bool(b: bool | None) -> str:
    if b is None:
        return "NULL"
    return "TRUE" if b else "FALSE"


def sql_num(v: float | int | None, digits: str | None = None) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        v = int(v)
    x = float(v)
    if digits == "int":
        return str(int(round(x)))
    return str(x)


def sql_ts_iso(iso: str | None) -> str:
    if not iso:
        return "NULL"
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return sql_escape(dt.astimezone(timezone.utc).isoformat()) + "::timestamptz"
    except ValueError:
        return sql_escape(iso) + "::timestamptz"


def sql_smallint(v: float | int | None) -> str:
    if v is None:
        return "NULL"
    return str(int(round(float(v))))


def min_temp_next_hours(data: dict[str, Any], hours: int, frost_c: float) -> tuple[bool, float | None]:
    """Return (any_below_threshold, min_temp_in_window)."""
    hourly = data.get("hourly") or {}
    times: list[str] = list(hourly.get("time") or [])
    temps: list[float | None] = list(hourly.get("temperature_2m") or [])
    if not times:
        return False, None
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    min_t: float | None = None
    for i, t in enumerate(times):
        if i >= len(temps):
            break
        try:
            tt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if tt.tzinfo is None:
                tt = tt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not (now <= tt <= end):
            continue
        tv = temps[i]
        if tv is None:
            continue
        tf = float(tv)
        if min_t is None or tf < min_t:
            min_t = tf
    if min_t is None:
        return False, None
    return min_t < frost_c, min_t


def emit_current(data: dict[str, Any]) -> None:
    cur = data.get("current") or {}
    frost_thr = _f("FROST_THRESHOLD_C", "2.0")
    spray_w = _f("SPRAY_WIND_MAX_MS", "5.0")
    spray_c = _f("SPRAY_CLOUD_MAX_PCT", "70")
    out_temp = _f("OUTDOOR_TEMP_MIN_C", "5.0")
    out_wind = _f("OUTDOOR_WIND_MAX_MS", "8.0")

    frost_risk, _ = min_temp_next_hours(data, 18, frost_thr)

    temp = cur.get("temperature_2m")
    wind = cur.get("wind_speed_10m")
    precip = cur.get("precipitation")
    rain = cur.get("rain")
    cloud = cur.get("cloud_cover")

    good_out = (
        temp is not None
        and wind is not None
        and precip is not None
        and float(temp) > out_temp
        and float(wind) < out_wind
        and float(precip) == 0.0
    )
    spray = (
        wind is not None
        and rain is not None
        and cloud is not None
        and float(wind) < spray_w
        and float(rain) == 0.0
        and float(cloud) < spray_c
    )

    pressure = cur.get("pressure_msl") or cur.get("surface_pressure")

    cols = [
        "id",
        "fetched_at",
        "temperature_c",
        "feels_like_c",
        "humidity_pct",
        "dewpoint_c",
        "wind_speed_ms",
        "wind_direction_deg",
        "wind_gusts_ms",
        "precipitation_mm",
        "rain_mm",
        "snowfall_cm",
        "cloud_cover_pct",
        "uv_index",
        "visibility_m",
        "pressure_hpa",
        "is_day",
        "weather_code",
        "frost_risk_tonight",
        "good_to_be_outside",
        "spray_safe",
    ]
    vals = [
        "1",
        "NOW()",
        sql_num(cur.get("temperature_2m")),
        sql_num(cur.get("apparent_temperature")),
        sql_smallint(cur.get("relative_humidity_2m")),
        sql_num(cur.get("dew_point_2m")),
        sql_num(cur.get("wind_speed_10m")),
        sql_smallint(cur.get("wind_direction_10m")),
        sql_num(cur.get("wind_gusts_10m")),
        sql_num(cur.get("precipitation")),
        sql_num(cur.get("rain")),
        sql_num(cur.get("snowfall")),
        sql_smallint(cur.get("cloud_cover")),
        sql_num(cur.get("uv_index")),
        (
            str(int(round(float(cur.get("visibility")))))
            if cur.get("visibility") is not None
            else "NULL"
        ),
        sql_num(pressure),
        sql_bool(cur.get("is_day")) if cur.get("is_day") is not None else "NULL",
        sql_smallint(cur.get("weather_code")),
        sql_bool(frost_risk),
        sql_bool(good_out),
        sql_bool(spray),
    ]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    print(
        "INSERT INTO weather.weather_current ("
        + ", ".join(cols)
        + ") VALUES ("
        + ", ".join(vals)
        + ") ON CONFLICT (id) DO UPDATE SET "
        + sets
        + ";"
    )


def emit_hourly(data: dict[str, Any]) -> None:
    hourly = data.get("hourly") or {}
    times: list[str] = list(hourly.get("time") or [])
    spray_w = _f("SPRAY_WIND_MAX_MS", "5.0")
    spray_c = _f("SPRAY_CLOUD_MAX_PCT", "70")
    out_temp_thr = _f("OUTDOOR_TEMP_MIN_C", "5.0")
    out_wind_thr = _f("OUTDOOR_WIND_MAX_MS", "8.0")

    keys = [
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation_probability",
        "precipitation",
        "rain",
        "snowfall",
        "weather_code",
        "cloud_cover",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
        "dew_point_2m",
        "uv_index",
    ]
    for i, t in enumerate(times[:48]):
        row: dict[str, Any] = {}
        for k in keys:
            arr = hourly.get(k) or []
            row[k] = arr[i] if i < len(arr) else None
        wind = row.get("wind_speed_10m")
        rain = row.get("rain")
        cloud = row.get("cloud_cover")
        temp = row.get("temperature_2m")
        pprob = row.get("precipitation_probability")
        spray_safe = (
            wind is not None
            and rain is not None
            and cloud is not None
            and float(wind) < spray_w
            and float(rain) == 0.0
            and float(cloud) < spray_c
        )
        good_out = (
            temp is not None
            and pprob is not None
            and wind is not None
            and float(temp) > out_temp_thr
            and float(pprob) < 20
            and float(wind) < out_wind_thr
        )
        vals = [
            "NOW()",
            sql_ts_iso(t),
            sql_num(row.get("temperature_2m")),
            sql_num(row.get("apparent_temperature")),
            sql_smallint(row.get("relative_humidity_2m")),
            sql_num(row.get("dew_point_2m")),
            sql_num(row.get("wind_speed_10m")),
            sql_smallint(row.get("wind_direction_10m")),
            sql_num(row.get("wind_gusts_10m")),
            sql_smallint(row.get("precipitation_probability")),
            sql_num(row.get("precipitation")),
            sql_num(row.get("rain")),
            sql_num(row.get("snowfall")),
            sql_smallint(row.get("cloud_cover")),
            sql_num(row.get("uv_index")),
            sql_smallint(row.get("weather_code")),
            sql_bool(spray_safe),
            sql_bool(good_out),
        ]
        print(
            "INSERT INTO weather.weather_forecast_hourly (fetched_at, forecast_time, temperature_c, feels_like_c, "
            "humidity_pct, dewpoint_c, wind_speed_ms, wind_direction_deg, wind_gusts_ms, precip_prob_pct, precip_mm, "
            "rain_mm, snowfall_cm, cloud_cover_pct, uv_index, weather_code, spray_safe, good_outdoor_window) VALUES ("
            + ", ".join(vals)
            + ");"
        )


def emit_daily(data: dict[str, Any]) -> None:
    daily = data.get("daily") or {}
    times: list[str] = list(daily.get("time") or [])
    frost_thr = _f("FROST_THRESHOLD_C", "2.0")
    heavy = _f("HEAVY_RAIN_MM", "15.0")

    for i, d in enumerate(times):
        tmax = (daily.get("temperature_2m_max") or [None] * len(times))[i]
        tmin = (daily.get("temperature_2m_min") or [None] * len(times))[i]
        prec_sum = (daily.get("precipitation_sum") or [None] * len(times))[i]
        pprob = (daily.get("precipitation_probability_max") or [None] * len(times))[i]
        rain_sum = (daily.get("rain_sum") or [None] * len(times))[i]
        snow_sum = (daily.get("snowfall_sum") or [None] * len(times))[i]
        wmax = (daily.get("wind_speed_10m_max") or [None] * len(times))[i]
        gmax = (daily.get("wind_gusts_10m_max") or [None] * len(times))[i]
        uvmax = (daily.get("uv_index_max") or [None] * len(times))[i]
        sr = (daily.get("sunrise") or [None] * len(times))[i]
        ss = (daily.get("sunset") or [None] * len(times))[i]
        wcode = (daily.get("weather_code") or [None] * len(times))[i]

        tmaxf = float(tmax) if tmax is not None else None
        tminf = float(tmin) if tmin is not None else None
        precf = float(prec_sum) if prec_sum is not None else None
        pprobf = float(pprob) if pprob is not None else None
        wmaxf = float(wmax) if wmax is not None else None

        frost_risk = tminf is not None and tminf < frost_thr
        heavy_rain = precf is not None and precf > heavy
        hdd = None
        if tmaxf is not None and tminf is not None:
            hdd = max(0.0, 18.0 - ((tmaxf + tminf) / 2.0))

        # Daily forecast often lacks humidity; laundry day uses precip/wind/prob only
        good_laundry = False
        if (
            precf is not None
            and precf == 0.0
            and pprobf is not None
            and pprobf < 20
            and wmaxf is not None
            and 2.0 <= wmaxf <= 6.0
        ):
            good_laundry = True

        vals = [
            "NOW()",
            sql_escape(d) + "::date",
            sql_num(tmax),
            sql_num(tmin),
            sql_num(prec_sum),
            sql_smallint(pprob),
            sql_num(rain_sum),
            sql_num(snow_sum),
            sql_num(wmax),
            sql_num(gmax),
            sql_num(uvmax),
            sql_ts_iso(sr) if sr else "NULL",
            sql_ts_iso(ss) if ss else "NULL",
            sql_smallint(wcode),
            sql_bool(frost_risk),
            sql_bool(heavy_rain),
            sql_bool(good_laundry),
            sql_num(hdd),
        ]
        print(
            "INSERT INTO weather.weather_forecast_daily (fetched_at, forecast_date, temp_max_c, temp_min_c, "
            "precip_sum_mm, precip_prob_max_pct, rain_sum_mm, snowfall_sum_cm, wind_speed_max_ms, wind_gusts_max_ms, "
            "uv_index_max, sunrise, sunset, weather_code, frost_risk, heavy_rain, good_laundry_day, heating_degree_days) "
            "VALUES (" + ", ".join(vals) + ") ON CONFLICT (forecast_date) DO UPDATE SET "
            "fetched_at = EXCLUDED.fetched_at, temp_max_c = EXCLUDED.temp_max_c, temp_min_c = EXCLUDED.temp_min_c, "
            "precip_sum_mm = EXCLUDED.precip_sum_mm, precip_prob_max_pct = EXCLUDED.precip_prob_max_pct, "
            "rain_sum_mm = EXCLUDED.rain_sum_mm, snowfall_sum_cm = EXCLUDED.snowfall_sum_cm, "
            "wind_speed_max_ms = EXCLUDED.wind_speed_max_ms, wind_gusts_max_ms = EXCLUDED.wind_gusts_max_ms, "
            "uv_index_max = EXCLUDED.uv_index_max, sunrise = EXCLUDED.sunrise, sunset = EXCLUDED.sunset, "
            "weather_code = EXCLUDED.weather_code, frost_risk = EXCLUDED.frost_risk, heavy_rain = EXCLUDED.heavy_rain, "
            "good_laundry_day = EXCLUDED.good_laundry_day, heating_degree_days = EXCLUDED.heating_degree_days;"
        )


def emit_archive(data: dict[str, Any]) -> None:
    daily = data.get("daily") or {}
    times: list[str] = list(daily.get("time") or [])
    for i, d in enumerate(times):
        tmax = (daily.get("temperature_2m_max") or [None] * len(times))[i]
        tmin = (daily.get("temperature_2m_min") or [None] * len(times))[i]
        tmean = (daily.get("temperature_2m_mean") or [None] * len(times))[i]
        prec = (daily.get("precipitation_sum") or [None] * len(times))[i]
        rain = (daily.get("rain_sum") or [None] * len(times))[i]
        snow = (daily.get("snowfall_sum") or [None] * len(times))[i]
        wmax = (daily.get("wind_speed_10m_max") or [None] * len(times))[i]
        wgmax = (daily.get("wind_gusts_10m_max") or [None] * len(times))[i]
        hmean = (daily.get("relative_humidity_2m_mean") or [None] * len(times))[i]
        dewm = (daily.get("dew_point_2m_mean") or [None] * len(times))[i]
        press = (daily.get("pressure_msl_mean") or [None] * len(times))[i]
        sun_sec = (daily.get("sunshine_duration") or [None] * len(times))[i]
        uv = (daily.get("uv_index_max") or [None] * len(times))[i]
        et0 = (daily.get("et0_fao_evapotranspiration") or [None] * len(times))[i]
        wcode = (daily.get("weather_code") or [None] * len(times))[i]

        tmeanf = float(tmean) if tmean is not None else None
        tminf = float(tmin) if tmin is not None else None
        frost_day = tminf is not None and tminf < 0.0
        gdd = max(0.0, (tmeanf - 10.0)) if tmeanf is not None else None
        sun_h = float(sun_sec) / 3600.0 if sun_sec is not None else None

        vals = [
            sql_escape(d) + "::date",
            sql_num(tmax),
            sql_num(tmin),
            sql_num(tmean),
            sql_num(prec),
            sql_num(rain),
            sql_num(snow),
            sql_num(wmax),
            sql_num(wgmax),
            sql_smallint(hmean),
            sql_num(dewm),
            sql_num(press),
            sql_num(sun_h),
            sql_num(uv),
            sql_num(et0),
            sql_smallint(wcode),
            sql_bool(frost_day),
            sql_num(gdd),
        ]
        print(
            "INSERT INTO weather.weather_log (log_date, temp_max_c, temp_min_c, temp_mean_c, precipitation_mm, rain_mm, "
            "snowfall_cm, wind_speed_max_ms, wind_gusts_max_ms, humidity_mean_pct, dewpoint_mean_c, pressure_mean_hpa, "
            "sunshine_hours, uv_index_max, et0_mm, weather_code, frost_day, gdd_base10) VALUES ("
            + ", ".join(vals)
            + ") ON CONFLICT (log_date) DO UPDATE SET "
            "temp_max_c = EXCLUDED.temp_max_c, temp_min_c = EXCLUDED.temp_min_c, temp_mean_c = EXCLUDED.temp_mean_c, "
            "precipitation_mm = EXCLUDED.precipitation_mm, rain_mm = EXCLUDED.rain_mm, snowfall_cm = EXCLUDED.snowfall_cm, "
            "wind_speed_max_ms = EXCLUDED.wind_speed_max_ms, wind_gusts_max_ms = EXCLUDED.wind_gusts_max_ms, "
            "humidity_mean_pct = EXCLUDED.humidity_mean_pct, dewpoint_mean_c = EXCLUDED.dewpoint_mean_c, "
            "pressure_mean_hpa = EXCLUDED.pressure_mean_hpa, sunshine_hours = EXCLUDED.sunshine_hours, "
            "uv_index_max = EXCLUDED.uv_index_max, et0_mm = EXCLUDED.et0_mm, weather_code = EXCLUDED.weather_code, "
            "frost_day = EXCLUDED.frost_day, gdd_base10 = EXCLUDED.gdd_base10;"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("current", "hourly", "daily", "archive"), required=True)
    ap.add_argument("--file", default=None)
    args = ap.parse_args()
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    if args.mode == "current":
        emit_current(data)
    elif args.mode == "hourly":
        emit_hourly(data)
    elif args.mode == "daily":
        emit_daily(data)
    else:
        emit_archive(data)


if __name__ == "__main__":
    main()
