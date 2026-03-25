# Setup Notes

## Local development

1. Clone repository.
2. Run `./install.sh`.
3. Fill `.env` values for your environment.
4. Validate with `openclaw health`.

## Re-running installer safely

- **User-owned docs** at the repo root — **`USER.md`**, **`SOUL.md`**, **`TOOLS.md`**, **`IDENTITY.md`**, **`HEARTBEAT.md`** — are **gitignored**. Starters ship under **`templates/`**; **`install.sh`** copies each to the root **only when that file is missing**, so **`git pull` / reinstall does not clobber** filled-in content.
- `.env` is not overwritten if it already exists.
- New keys in `.env.example` (e.g. **`GARDENGNOME_DATABASE_URL`**) must be merged into an existing **`.env`** by hand.
- When **`GARDENGNOME_DATABASE_URL`** is set, the installer **requires `psql`** on `PATH` (or offers to install **`postgresql-client`** / **`libpq`** in interactive mode). Then **`install/setup_db.sh`** runs **`psql`** `SELECT 1`, applies **pending** core **`db/postgres/*.sql`** unless **`GARDENGNOME_DB_APPLY_SCHEMA=0`**, and handles seeds per **`GARDENGNOME_DB_APPLY_SEEDS`** (**`0`** / **`auto`** / **`1`**). **`GARDENGNOME_DB_SKIP_INIT=1`** skips prompts, the **`psql`** check, connectivity test, migrations, and seeds.
- Existing agent registration is detected and skipped.
- Cron step is scaffold-only (no real schedules yet).
- Verification can be run directly with `bash install/verify.sh`.

## Constrained-LLM database (optional)

1. Set **`GARDENGNOME_DATABASE_URL`**, then run **`bash install/setup_db.sh "$GARDENGNOME_ROOT"`** (or the installer). Core **`db/postgres/*.sql`** runs in sort order, **omitting** migrations already in **`schema_migrations`** (disable DDL with **`GARDENGNOME_DB_APPLY_SCHEMA=0`**). Seeds: **`auto`** (default) adds example rows when **`sender_profiles`** is empty; **`1`** always; **`0`** never. Or apply **`psql … -f db/postgres/seeds/003_example_openclaw_context.sql`** / **`seed-examples`** manually.
2. For semantic cache / RAG, run **Qdrant** and **Ollama** with an embedding-capable model; copy **`OLLAMA_*`**, **`QDRANT_*`**, and score thresholds from **`.env.example`** into **`.env`**.
3. Install Python deps: **`pip install -r install/requirements-constrained-llm.txt`**.
4. Optionally: **`python3 scripts/constrained_llm_pipeline.py seed-examples`**, then **`warmup-semantic-cache`** / **`warmup-rag-chunk`** to embed and index content.
5. **`python3 scripts/constrained_llm_pipeline.py pipeline --message "your test"`** prints the routing/cache/RAG/context decision JSON for integration testing.

## First run / agent onboarding (`/gnome`)

1. **State file:** the agent uses **`.openclaw/gardengnome-state.json`** (gitignored). Template: **`config/gardengnome-state.example.json`**. Tracks profile, identity, location, **`onboarding.postLocationBootstrapAt`**, and **`weather.historicalBackfillAt`**.
2. **Location:** city, address, or lat/lon. Use **`python3 scripts/geocode_garden.py`** — **`search`** lists candidates (refine if none); user must **confirm** before **`apply-search`** or **`apply-coords`**. **`smoke`** checks bounds and a minimal Open-Meteo forecast (and prints an inferred **IANA timezone**). **`apply-coords`** can omit **`--timezone`**; Open-Meteo supplies **`GARDEN_TIMEZONE`**. Profile onboarding should not ask for timezone separately when location will set it; sync **`USER.md`** from **`config/garden.env`** after location. See **`AGENTS.md`** for the full `/gnome` checklist.
3. **Post-location bootstrap:** After name + location are saved in state, the agent must apply default **`IDENTITY.md`** (from **`templates/IDENTITY.md`**), ensure **`avatars/openclaw.png`** exists, launch historical backfill (**`nohup python3 scripts/weather_historical_backfill.py >> tmp/weather_backfill.log 2>&1 &`** when **`weather.historicalBackfillAt`** is still unset) so **`garden.weather_log`** can populate (**`GARDEN_DB_URL`**, network, migration **`004`**), set **`onboarding.postLocationBootstrapAt`**, then send the scripted prompt in **`AGENTS.md`**. The backfill script writes **`weather.historicalBackfillAt`** to **`.openclaw/gardengnome-state.json`** when the process exits successfully.

## Weather stack

1. Apply **`db/postgres/004_garden_weather.sql`** via **`install/setup_db.sh`** (included with other pending migrations unless **`GARDENGNOME_DB_APPLY_SCHEMA=0`**).
2. **`install.sh`** creates **`config/garden.env`** from the template when missing and syncs **`GARDEN_DB_URL`** from **`GARDENGNOME_DATABASE_URL`** when possible; edit coordinates and thresholds there. **`pip install`** for weather/constrained-LLM requirements runs during install unless skipped.
3. **`bash scripts/weather_current.sh`** — first fill of **`garden.weather_*`**; then **`python3 scripts/weather_historical_backfill.py`** optional.
4. User timers: **`bash scripts/setup_cron.sh`** (or **`GARDENGNOME_SETUP_SYSTEMD_TIMERS=1`** on install). For timers to run when logged out, enable **linger**: `loginctl enable-linger "$USER"`.
5. **`bash scripts/daily_briefing.sh`** needs Ollama at **`OLLAMA_HOST`** if you want prose (otherwise JSON-only fallback).

**Python packages:** **`./install.sh`** installs **`install/requirements-weather.txt`** and **`install/requirements-constrained-llm.txt`** after repo bootstrap (requires **`python3 -m pip`**). Skip with **`GARDENGNOME_SKIP_PIP_REQUIREMENTS=1`**.

## Troubleshooting

- `openclaw: command not found`: install OpenClaw CLI and rerun.
- `node` or `python3` missing: install required runtime and rerun.
- Agent missing from **`openclaw agents list`**: re-run `./install.sh` or run `openclaw agents add` with the same `--workspace` as `GARDENGNOME_ROOT`.
- Agent in CLI / **Agents** tab but not under **Sessions** in the Control UI: the UI session list is empty until a gateway session exists. Run `./install.sh` (it bootstraps one turn when needed), or manually: `openclaw agent --agent gardengnome --message "Hello" --json`. To skip the automatic bootstrap turn, set `GARDENGNOME_BOOTSTRAP_SESSION=0`.
- Chat only talks to **main**: use the Control UI **Chat** agent picker and choose `gardengnome` (or your `AGENT_NAME`).
