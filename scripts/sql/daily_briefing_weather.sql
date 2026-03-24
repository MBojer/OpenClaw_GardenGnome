-- Weather JSON context for daily briefing (inject into local Qwen prompt).
SELECT row_to_json(t) FROM (
    SELECT
        c.temperature_c,
        c.feels_like_c,
        c.humidity_pct,
        c.wind_speed_ms,
        c.wind_gusts_ms,
        c.precipitation_mm AS precip_last_hour_mm,
        c.uv_index,
        c.frost_risk_tonight,
        c.good_to_be_outside,
        c.spray_safe,
        c.fetched_at,
        (SELECT json_agg(row_to_json(d)) FROM (
            SELECT forecast_date, temp_max_c, temp_min_c, precip_sum_mm,
                   precip_prob_max_pct, frost_risk, good_laundry_day, weather_code
            FROM garden.weather_forecast_daily
            ORDER BY forecast_date LIMIT 7
        ) d) AS forecast_7day,
        (SELECT row_to_json(r) FROM garden.weather_recent_summary r) AS last_14_days,
        (SELECT row_to_json(n) FROM garden.weather_next_24h n) AS next_24h,
        (SELECT json_agg(row_to_json(a)) FROM garden.weather_alerts a
            WHERE resolved_at IS NULL) AS active_alerts
    FROM garden.weather_current c
    WHERE c.id = 1
) t;
