-- Garden weather schema (Open-Meteo ingestion). Archive API has ~5 day lag; jobs use CURRENT_DATE - 6.
-- Applied after 002 by install/setup_db.sh when schema apply is enabled (default; see GARDENGNOME_DB_APPLY_SCHEMA).

BEGIN;

CREATE SCHEMA IF NOT EXISTS weather;

CREATE TABLE IF NOT EXISTS weather.weather_current (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    fetched_at          TIMESTAMPTZ NOT NULL,
    temperature_c       NUMERIC(5,2),
    feels_like_c        NUMERIC(5,2),
    humidity_pct        SMALLINT,
    dewpoint_c          NUMERIC(5,2),
    wind_speed_ms       NUMERIC(5,2),
    wind_direction_deg  SMALLINT,
    wind_gusts_ms       NUMERIC(5,2),
    precipitation_mm    NUMERIC(6,2),
    rain_mm             NUMERIC(6,2),
    snowfall_cm         NUMERIC(6,2),
    cloud_cover_pct     SMALLINT,
    uv_index            NUMERIC(4,2),
    visibility_m        INTEGER,
    pressure_hpa        NUMERIC(7,2),
    is_day              BOOLEAN,
    weather_code        SMALLINT,
    frost_risk_tonight  BOOLEAN,
    good_to_be_outside  BOOLEAN,
    spray_safe          BOOLEAN,
    CONSTRAINT weather_current_single_row CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS weather.weather_forecast_hourly (
    id                  BIGSERIAL PRIMARY KEY,
    fetched_at          TIMESTAMPTZ NOT NULL,
    forecast_time       TIMESTAMPTZ NOT NULL,
    temperature_c       NUMERIC(5,2),
    feels_like_c        NUMERIC(5,2),
    humidity_pct        SMALLINT,
    dewpoint_c          NUMERIC(5,2),
    wind_speed_ms       NUMERIC(5,2),
    wind_direction_deg  SMALLINT,
    wind_gusts_ms       NUMERIC(5,2),
    precip_prob_pct     SMALLINT,
    precip_mm           NUMERIC(6,2),
    rain_mm             NUMERIC(6,2),
    snowfall_cm         NUMERIC(6,2),
    cloud_cover_pct     SMALLINT,
    uv_index            NUMERIC(4,2),
    weather_code        SMALLINT,
    spray_safe          BOOLEAN,
    good_outdoor_window BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_forecast_hourly_time
    ON weather.weather_forecast_hourly (forecast_time);

CREATE TABLE IF NOT EXISTS weather.weather_forecast_daily (
    id                  BIGSERIAL PRIMARY KEY,
    fetched_at          TIMESTAMPTZ NOT NULL,
    forecast_date       DATE NOT NULL UNIQUE,
    temp_max_c          NUMERIC(5,2),
    temp_min_c          NUMERIC(5,2),
    precip_sum_mm       NUMERIC(6,2),
    precip_prob_max_pct SMALLINT,
    rain_sum_mm         NUMERIC(6,2),
    snowfall_sum_cm     NUMERIC(6,2),
    wind_speed_max_ms   NUMERIC(5,2),
    wind_gusts_max_ms   NUMERIC(5,2),
    uv_index_max        NUMERIC(4,2),
    sunrise             TIMESTAMPTZ,
    sunset              TIMESTAMPTZ,
    weather_code        SMALLINT,
    frost_risk          BOOLEAN,
    heavy_rain          BOOLEAN,
    good_laundry_day    BOOLEAN,
    heating_degree_days NUMERIC(5,2)
);

CREATE TABLE IF NOT EXISTS weather.weather_log (
    log_date            DATE PRIMARY KEY,
    temp_max_c          NUMERIC(5,2),
    temp_min_c          NUMERIC(5,2),
    temp_mean_c         NUMERIC(5,2),
    precipitation_mm    NUMERIC(6,2),
    rain_mm             NUMERIC(6,2),
    snowfall_cm         NUMERIC(6,2),
    wind_speed_max_ms   NUMERIC(5,2),
    wind_gusts_max_ms   NUMERIC(5,2),
    humidity_mean_pct   SMALLINT,
    dewpoint_mean_c     NUMERIC(5,2),
    pressure_mean_hpa   NUMERIC(7,2),
    sunshine_hours      NUMERIC(5,2),
    uv_index_max        NUMERIC(4,2),
    et0_mm              NUMERIC(6,2),
    weather_code        SMALLINT,
    frost_day           BOOLEAN,
    gdd_base10          NUMERIC(5,2),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weather.weather_alerts (
    id          BIGSERIAL PRIMARY KEY,
    alert_type  TEXT NOT NULL,
    severity    TEXT,
    message     TEXT NOT NULL,
    valid_from  TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_active
    ON weather.weather_alerts (resolved_at)
    WHERE resolved_at IS NULL;

CREATE OR REPLACE VIEW weather.weather_recent_summary AS
SELECT
    COUNT(*) FILTER (WHERE frost_day)       AS frost_days,
    SUM(precipitation_mm)                   AS total_precip_mm,
    AVG(temp_mean_c)                        AS avg_temp_c,
    MAX(temp_max_c)                         AS max_temp_c,
    MIN(temp_min_c)                         AS min_temp_c,
    SUM(gdd_base10)                         AS cumulative_gdd,
    COUNT(*) FILTER (WHERE precipitation_mm = 0) AS dry_days
FROM weather.weather_log
WHERE log_date >= CURRENT_DATE - INTERVAL '14 days';

CREATE OR REPLACE VIEW weather.weather_next_24h AS
SELECT
    MIN(temperature_c)                      AS temp_min_c,
    MAX(temperature_c)                      AS temp_max_c,
    SUM(precip_mm)                          AS total_precip_mm,
    MAX(precip_prob_pct)                    AS max_precip_prob,
    MAX(wind_gusts_ms)                      AS max_wind_gusts_ms,
    BOOL_OR(spray_safe)                     AS any_spray_window,
    BOOL_AND(NOT spray_safe)                AS no_spray_window,
    (MIN(temperature_c) < 2.0)              AS frost_risk
FROM weather.weather_forecast_hourly
WHERE forecast_time BETWEEN NOW() AND NOW() + INTERVAL '24 hours';

CREATE OR REPLACE VIEW weather.weather_gdd_season AS
SELECT
    SUM(gdd_base10) AS gdd_this_year,
    (
        SELECT AVG(annual_gdd) FROM (
            SELECT EXTRACT(YEAR FROM log_date) AS yr, SUM(gdd_base10) AS annual_gdd
            FROM weather.weather_log
            WHERE EXTRACT(DOY FROM log_date) <= EXTRACT(DOY FROM CURRENT_DATE)
              AND EXTRACT(YEAR FROM log_date) < EXTRACT(YEAR FROM CURRENT_DATE)
            GROUP BY yr
        ) hist
    ) AS gdd_historical_avg
FROM weather.weather_log
WHERE EXTRACT(YEAR FROM log_date) = EXTRACT(YEAR FROM CURRENT_DATE);

INSERT INTO schema_migrations (id) VALUES ('004_garden_weather') ON CONFLICT DO NOTHING;

COMMIT;
