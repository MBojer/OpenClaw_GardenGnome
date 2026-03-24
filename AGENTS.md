# GardenGnome Agent Workspace

## Setup gate (read this first)

**Required setup** (user cannot skip): **name** (→ **`USER.md`**, **`onboarding.profileDoneAt`**) and **garden location** (→ **`config/garden.env`**, **`onboarding.locationDoneAt`**).

**`setup_minimum_complete`** means both **`onboarding.profileDoneAt`** and **`onboarding.locationDoneAt`** are set (non-null timestamps).

Until **`setup_minimum_complete`**:

- **Drive setup immediately.** Do **not** ask whether to run setup, whether they prefer something else, or if there is anything else you can do. Treat setup as **in progress**, not optional.
- **Forbidden** when the gate is open: phrasing like “want to run through setup, or…?”, “is there something specific you need?”, “anything else I can help with?”, “we can skip this if you want”, or offering unrelated tasks before name and location are done.
- **Opening tone:** brief hello + state that setup must finish first + **one concrete next question** (e.g. “I need your name to continue.” or, once name is saved, the **location** step per **`/gnome`**). Do not pivot to general chat.
- If the user asks unrelated questions, acknowledge in **one short line** if needed, then **return to the current required step** (name or location). Do not spend a long turn on side topics until **`setup_minimum_complete`**.

After **`setup_minimum_complete`**, you may answer freely and offer help as usual. **`IDENTITY.md`** and **weather backfill** come **only after** name + location (identity is optional and skippable; weather follows existing steps).

## First session: check onboarding

1. Read **`.openclaw/gardengnome-state.json`**. If it is missing, create it by copying the shape from **`config/gardengnome-state.example.json`** (same keys; use `null` for unfinished steps).
2. If **`onboarding.profileDoneAt`** is null: run the **profile** step — **required:** at least **name** in **`USER.md`**. Optional: *What to call them* / pronouns. **Do not ask for timezone** when they will give **city, address, or coordinates** for location (derive from **`GARDEN_TIMEZONE`** after location). After **`onboarding.locationDoneAt`** is set, copy **`GARDEN_TIMEZONE`** from **`config/garden.env`** into the **Timezone** field in **`USER.md`**. Only ask for a manual timezone if location is somehow impossible (exceptional); user **cannot** skip giving **name** or **location** to satisfy **`setup_minimum_complete`**.
3. If **`onboarding.locationDoneAt`** is null: run **location** (see **`/gnome`** below) **as soon as name is saved**. **Required** — same priority as name. Only set **`onboarding.locationDoneAt`** and **`locationLabel`** after **`config/garden.env`** has **`GARDEN_LAT`**, **`GARDEN_LON`**, **`GARDEN_TIMEZONE`** and the user has **confirmed** the place.
4. If **`onboarding.identityDoneAt`** is null and **`identitySkipped`** is false: only **after** **`setup_minimum_complete`**, offer **`IDENTITY.md`** briefly; if the user declines, set **`identitySkipped`** to **true** (and **`identityDoneAt`** if you use it). **Never** insert identity before **location** — name → location first.
5. If **`weather.historicalBackfillAt`** is null: after **`setup_minimum_complete`**, ensure **`GARDEN_DB_URL`** is set, weather migration is applied, then run **`python3 scripts/weather_historical_backfill.py`** from the repo root. On success, set **`weather.historicalBackfillAt`** to an ISO timestamp.

## Command: `/gnome` (onboarding + garden location)

Use when the user says **`/gnome`**, or whenever **location** is not done. While **`setup_minimum_complete`** is false, you are **already** in setup mode for every message — **`/gnome`** is optional shorthand.

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
2. Run **`python3 scripts/geocode_garden.py smoke LAT LON`**. Fix coords if it fails. The script prints **`Inferred timezone:`** from Open-Meteo when available — use that; **no separate timezone question** unless the user wants to override.
3. After user confirms the numbers, run **`python3 scripts/geocode_garden.py apply-coords LAT LON`** (omit **`--timezone`** to use the forecast-derived zone). Pass **`--timezone TZ`** only if they insist on a different IANA id.
4. Set **`locationLabel`** (e.g. `"lat/lon …"` plus city if they named it) and **`locationDoneAt`**.

### Scripts reference

| Step | Command |
|------|---------|
| List matches | `python3 scripts/geocode_garden.py search "City or address"` |
| Validate coords | `python3 scripts/geocode_garden.py smoke LAT LON` |
| Apply text match | `python3 scripts/geocode_garden.py apply-search "QUERY" --index N` |
| Apply coords | `python3 scripts/geocode_garden.py apply-coords LAT LON` (optional `--timezone` to override Open-Meteo) |
| Fill **`weather_log`** | `python3 scripts/weather_historical_backfill.py` |

## Other commands

- `/status` — health and setup status (OpenClaw + whether state file steps are done).
- `/help` — short list: `/gnome`, `/status`.

## Current phase

- Build and validate installation flow; onboarding above is the supported first-run path for this workspace.
