# Setup Notes

## Local development

1. Clone repository.
2. Run `./install.sh`.
3. Fill `.env` values for your environment.
4. Validate with `openclaw health`.

## Re-running installer safely

- `.env` is not overwritten if it already exists.
- New keys in `.env.example` (e.g. **`GARDENGNOME_DATABASE_URL`**) must be merged into an existing **`.env`** by hand.
- When **`GARDENGNOME_DATABASE_URL`** is set, the installer **requires `psql`** on `PATH` (or offers to install **`postgresql-client`** / **`libpq`** in interactive mode). Then **`install/setup_db.sh`** runs **`psql`** `SELECT 1`. Schema apply runs only when **`GARDENGNOME_DB_APPLY_SCHEMA=1`**. **`GARDENGNOME_DB_SKIP_INIT=1`** skips prompts, the **`psql`** check, connectivity test, and schema.
- Existing agent registration is detected and skipped.
- Cron step is scaffold-only (no real schedules yet).
- Verification can be run directly with `bash install/verify.sh`.

## Constrained-LLM database (optional)

1. Set **`GARDENGNOME_DATABASE_URL`** and **`GARDENGNOME_DB_APPLY_SCHEMA=1`**, then run **`bash install/setup_db.sh "$GARDENGNOME_ROOT"`** (or the installer). Core **`db/postgres/*.sql`** runs in sort order, **omitting** migrations already in **`schema_migrations`**, and **never** applies **`db/postgres/seeds/*.sql`** unless **`GARDENGNOME_DB_APPLY_SEEDS=1`**. For optional starter rows: **`psql … -f db/postgres/seeds/003_example_openclaw_context.sql`** or the **`seed-examples`** Python command.
2. For semantic cache / RAG, run **Qdrant** and **Ollama** with an embedding-capable model; copy **`OLLAMA_*`**, **`QDRANT_*`**, and score thresholds from **`.env.example`** into **`.env`**.
3. Install Python deps: **`pip install -r install/requirements-constrained-llm.txt`**.
4. Optionally: **`python3 scripts/constrained_llm_pipeline.py seed-examples`**, then **`warmup-semantic-cache`** / **`warmup-rag-chunk`** to embed and index content.
5. **`python3 scripts/constrained_llm_pipeline.py pipeline --message "your test"`** prints the routing/cache/RAG/context decision JSON for integration testing.

## Weather stack

1. Apply **`db/postgres/004_garden_weather.sql`** via **`GARDENGNOME_DB_APPLY_SCHEMA=1`** and **`install/setup_db.sh`**.
2. **`cp config/garden.env.template config/garden.env`** and set **`GARDEN_DB_URL`**, coordinates, thresholds; **`pip install -r install/requirements-weather.txt`**.
3. **`bash scripts/weather_current.sh`** — first fill of **`garden.weather_*`**; then **`python3 scripts/weather_historical_backfill.py`** optional.
4. User timers: **`bash scripts/setup_cron.sh`** (or **`GARDENGNOME_SETUP_SYSTEMD_TIMERS=1`** on install). For timers to run when logged out, enable **linger**: `loginctl enable-linger "$USER"`.
5. **`bash scripts/daily_briefing.sh`** needs Ollama at **`OLLAMA_HOST`** if you want prose (otherwise JSON-only fallback).

## Troubleshooting

- `openclaw: command not found`: install OpenClaw CLI and rerun.
- `node` or `python3` missing: install required runtime and rerun.
- Agent missing from **`openclaw agents list`**: re-run `./install.sh` or run `openclaw agents add` with the same `--workspace` as `GARDENGNOME_ROOT`.
- Agent in CLI / **Agents** tab but not under **Sessions** in the Control UI: the UI session list is empty until a gateway session exists. Run `./install.sh` (it bootstraps one turn when needed), or manually: `openclaw agent --agent gardengnome --message "Hello" --json`. To skip the automatic bootstrap turn, set `GARDENGNOME_BOOTSTRAP_SESSION=0`.
- Chat only talks to **main**: use the Control UI **Chat** agent picker and choose `gardengnome` (or your `AGENT_NAME`).
