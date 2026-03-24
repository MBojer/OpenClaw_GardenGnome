# GardenGnome Agent Workspace

## First session: check onboarding

1. Read **`.openclaw/gardengnome-state.json`**. If it is missing, create it by copying the shape from **`config/gardengnome-state.example.json`** (same keys; use `null` for unfinished steps).
2. If **`onboarding.profileDoneAt`** is null: run the **profile** step — fill at least **name** and **timezone** in **`USER.md`**, then set **`onboarding.profileDoneAt`** to an ISO-8601 UTC timestamp.
3. If **`onboarding.identityDoneAt`** is null and **`identitySkipped`** is false: help fill **`IDENTITY.md`**, or if the user declines, set **`identitySkipped`** to **true** (and optionally **`identityDoneAt`** to now).
4. If **`onboarding.locationDoneAt`** is null: run **location** (see **`/gnome`** below). Only set **`onboarding.locationDoneAt`** and **`locationLabel`** after **`config/garden.env`** has the final **`GARDEN_LAT`**, **`GARDEN_LON`**, **`GARDEN_TIMEZONE`** and the user has **explicitly confirmed** the place.
5. If **`weather.historicalBackfillAt`** is null: ensure **`GARDEN_DB_URL`** is set, weather migration is applied, then run **`python3 scripts/weather_historical_backfill.py`** from the repo root. On success, set **`weather.historicalBackfillAt`** to an ISO timestamp.

## Command: `/gnome` (onboarding + garden location)

Use when the user wants setup, or when onboarding is incomplete.

### Location rules

- Accept **city**, **approximate place**, **address**, or **lat/lon**. City-level accuracy is fine for weather.
- **Never** write **`config/garden.env`** or set **`locationDoneAt`** until the user has **confirmed** the resolved place and tooling has **validated** it.

### Flow (text: city / address / place)

1. Run **`python3 scripts/geocode_garden.py search "QUERY"`** (adjust **`--count`** if needed). Exit code **1** means no matches — ask for a clearer query (country, spelling).
2. If **multiple** lines are printed, show them to the user and ask which **1-based index** is correct (or a refined query). **Single** result: still show **name, lat, lon, timezone** and ask for a clear **yes** before applying.
3. Optional double-check before apply: **`python3 scripts/geocode_garden.py smoke LAT LON`** (bounds + Open-Meteo forecast sanity check).
4. After confirmation, run **`python3 scripts/geocode_garden.py apply-search "SAME_QUERY" --index N`** using the **same** query and **`--count`** as in step 1 so the index matches the list the user saw.
5. Set **`onboarding.locationLabel`** to the human-readable place (e.g. `Oslo, Oslo County, Norway`) and **`onboarding.locationDoneAt`** to now.

### Flow (coordinates)

1. Parse **lat** and **lon**; valid ranges are **[-90, 90]** and **[-180, 180]**.
2. Run **`python3 scripts/geocode_garden.py smoke LAT LON`**. Fix coords if it fails.
3. Ask for **IANA timezone** (**`GARDEN_TIMEZONE`**, e.g. `Europe/Oslo`) if not already known — required for **`apply-coords`**.
4. After user confirms the numbers (and timezone), run **`python3 scripts/geocode_garden.py apply-coords LAT LON --timezone TZ`**.
5. Set **`locationLabel`** (e.g. `"lat/lon …"`) and **`locationDoneAt`**.

### Scripts reference

| Step | Command |
|------|---------|
| List matches | `python3 scripts/geocode_garden.py search "City or address"` |
| Validate coords | `python3 scripts/geocode_garden.py smoke LAT LON` |
| Apply text match | `python3 scripts/geocode_garden.py apply-search "QUERY" --index N` |
| Apply coords | `python3 scripts/geocode_garden.py apply-coords LAT LON --timezone TZ` |
| Fill **`weather_log`** | `python3 scripts/weather_historical_backfill.py` |

## Other commands

- `/status` — health and setup status (OpenClaw + whether state file steps are done).
- `/help` — short list: `/gnome`, `/status`.

## Current phase

- Build and validate installation flow; onboarding above is the supported first-run path for this workspace.
