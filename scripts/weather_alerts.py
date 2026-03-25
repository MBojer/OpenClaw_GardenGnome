#!/usr/bin/env python3
"""
Evaluate weather.weather_* tables and maintain weather.weather_alerts.
Requires: pip install -r install/requirements-weather.txt
Environment: GARDEN_DB_URL (and thresholds from config/garden.env if sourced by wrapper).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

try:
    import psycopg
except ImportError:
    print("Install psycopg: pip install -r install/requirements-weather.txt", file=sys.stderr)
    raise SystemExit(1) from None


def _f(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def connect():
    url = os.environ.get("GARDEN_DB_URL")
    if not url:
        print("GARDEN_DB_URL not set", file=sys.stderr)
        raise SystemExit(1)
    return psycopg.connect(url)


def resolve_expired(cur) -> None:
    cur.execute(
        """
        UPDATE weather.weather_alerts
        SET resolved_at = NOW()
        WHERE resolved_at IS NULL
          AND valid_until IS NOT NULL
          AND valid_until < NOW();
        """
    )


def resolve_type(cur, alert_type: str) -> None:
    cur.execute(
        """
        UPDATE weather.weather_alerts
        SET resolved_at = NOW()
        WHERE resolved_at IS NULL AND alert_type = %s;
        """,
        (alert_type,),
    )


def upsert_alert(cur, alert_type: str, severity: str, message: str, vf, vu) -> None:
    cur.execute(
        """
        INSERT INTO weather.weather_alerts (alert_type, severity, message, valid_from, valid_until)
        VALUES (%s, %s, %s, %s, %s);
        """,
        (alert_type, severity, message, vf, vu),
    )


def main() -> None:
    frost_thr = _f("FROST_THRESHOLD_C", "2.0")
    heavy_mm = _f("HEAVY_RAIN_MM", "15.0")
    heat_thr = _f("HEAT_THRESHOLD_C", "28.0")
    wind_gust = _f("HIGH_WIND_GUST_MS", "12.0")
    need_spray = int(os.environ.get("HOURLY_SPRAY_CONSECUTIVE", "3"))

    today = date.today()
    with connect() as conn:
        with conn.cursor() as cur:
            resolve_expired(cur)

            # frost: hourly next 18h temp < threshold
            cur.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM weather.weather_forecast_hourly
                  WHERE forecast_time >= NOW()
                    AND forecast_time <= NOW() + INTERVAL '18 hours'
                    AND temperature_c < %s
                );
                """,
                (frost_thr,),
            )
            frost_ok = cur.fetchone()[0]
            resolve_type(cur, "frost")
            if frost_ok:
                upsert_alert(
                    cur,
                    "frost",
                    "warning",
                    f"Temperature may drop below {frost_thr}°C within 18 hours.",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(hours=18),
                )

            # heavy_rain: daily next 3 days
            cur.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM weather.weather_forecast_daily
                  WHERE forecast_date > CURRENT_DATE
                    AND forecast_date <= CURRENT_DATE + 3
                    AND precip_sum_mm > %s
                );
                """,
                (heavy_mm,),
            )
            heavy_ok = cur.fetchone()[0]
            resolve_type(cur, "heavy_rain")
            if heavy_ok:
                upsert_alert(
                    cur,
                    "heavy_rain",
                    "advisory",
                    f"Heavy rain possible (> {heavy_mm} mm) in the next 3 days.",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(days=3),
                )

            # high_wind: gusts next 12h
            cur.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM weather.weather_forecast_hourly
                  WHERE forecast_time >= NOW()
                    AND forecast_time <= NOW() + INTERVAL '12 hours'
                    AND wind_gusts_ms > %s
                );
                """,
                (wind_gust,),
            )
            wind_ok = cur.fetchone()[0]
            resolve_type(cur, "high_wind")
            if wind_ok:
                upsert_alert(
                    cur,
                    "high_wind",
                    "watch",
                    f"Wind gusts above {wind_gust} m/s possible within 12 hours.",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(hours=12),
                )

            # heat: daily max > threshold in next 3 days
            cur.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM weather.weather_forecast_daily
                  WHERE forecast_date > CURRENT_DATE
                    AND forecast_date <= CURRENT_DATE + 3
                    AND temp_max_c > %s
                );
                """,
                (heat_thr,),
            )
            heat_ok = cur.fetchone()[0]
            resolve_type(cur, "heat")
            if heat_ok:
                upsert_alert(
                    cur,
                    "heat",
                    "advisory",
                    f"Hot weather (max > {heat_thr}°C) possible in the next few days.",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(days=3),
                )

            # spray_window: need_spray consecutive hours spray_safe in next 24h
            cur.execute(
                """
                WITH h AS (
                  SELECT forecast_time, spray_safe,
                    row_number() OVER (ORDER BY forecast_time)
                      - row_number() OVER (PARTITION BY spray_safe ORDER BY forecast_time) AS grp
                  FROM weather.weather_forecast_hourly
                  WHERE forecast_time >= NOW()
                    AND forecast_time <= NOW() + INTERVAL '24 hours'
                ),
                streaks AS (
                  SELECT COUNT(*) AS n FROM h WHERE spray_safe GROUP BY grp
                )
                SELECT COALESCE((SELECT MAX(n) FROM streaks), 0) >= %s;
                """,
                (need_spray,),
            )
            row_sp = cur.fetchone()
            spray_ok = bool(row_sp and row_sp[0])
            resolve_type(cur, "spray_window")
            if spray_ok:
                upsert_alert(
                    cur,
                    "spray_window",
                    "advisory",
                    "Several consecutive hours look safe for spraying (low wind, dry).",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc) + timedelta(hours=24),
                )

            # good_laundry: tomorrow
            tomorrow = today + timedelta(days=1)
            cur.execute(
                """
                SELECT good_laundry_day FROM weather.weather_forecast_daily
                WHERE forecast_date = %s;
                """,
                (tomorrow,),
            )
            row = cur.fetchone()
            laundry_ok = bool(row and row[0])
            resolve_type(cur, "good_laundry")
            if laundry_ok:
                upsert_alert(
                    cur,
                    "good_laundry",
                    "advisory",
                    "Tomorrow looks like a good laundry-drying day.",
                    datetime.now(timezone.utc),
                    datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=timezone.utc)
                    + timedelta(days=1),
                )

        conn.commit()
    print("weather_alerts: OK")


if __name__ == "__main__":
    main()
