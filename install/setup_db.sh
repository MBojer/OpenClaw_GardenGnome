#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

ENV_FILE="$ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "WARN: No .env in $ROOT — skipping database steps."
  exit 0
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

db_url_raw="${GARDENGNOME_DATABASE_URL-}"
# Trim surrounding quotes from manual .env edits
db_url="${db_url_raw#\"}"
db_url="${db_url%\"}"
db_url="${db_url#\'}"
db_url="${db_url%\'}"

if [[ "${GARDENGNOME_DB_SKIP_INIT:-0}" == "1" ]]; then
  echo "GARDENGNOME_DB_SKIP_INIT=1 — skipping database steps."
  exit 0
fi

if [[ -z "$db_url" ]]; then
  echo "No GARDENGNOME_DATABASE_URL — skipping DB connectivity test and schema (configure .env or export the URL for the installer)."
  exit 0
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "WARN: GARDENGNOME_DATABASE_URL is set but psql is not installed — cannot test connectivity or apply schema."
  echo "      Install PostgreSQL client tools, then run: bash install/setup_db.sh $ROOT"
  exit 0
fi

echo "Testing PostgreSQL connectivity…"
if ! psql "$db_url" -v ON_ERROR_STOP=1 -c "SELECT 1" >/dev/null 2>&1; then
  echo "WARN: Could not connect with GARDENGNOME_DATABASE_URL (check URL, network, SSL, and that the database exists)."
  exit 0
fi
echo "PostgreSQL connectivity OK."

if [[ "${GARDENGNOME_DB_APPLY_SCHEMA:-0}" != "1" ]]; then
  echo "Schema not applied (set GARDENGNOME_DB_APPLY_SCHEMA=1 to run db/postgres/*.sql)."
  exit 0
fi

sql_dir="$ROOT/db/postgres"
if [[ ! -d "$sql_dir" ]]; then
  echo "ERROR: Missing $sql_dir"
  exit 0
fi

shopt -s nullglob
files=("$sql_dir"/*.sql)
shopt -u nullglob
if ((${#files[@]} == 0)); then
  echo "WARN: No .sql files in $sql_dir"
  exit 0
fi

for f in "${files[@]}"; do
  echo "Applying $(basename "$f") …"
  psql "$db_url" -v ON_ERROR_STOP=1 -f "$f"
done
echo "PostgreSQL schema applied."
