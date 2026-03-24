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
  echo "Schema not applied (set GARDENGNOME_DB_APPLY_SCHEMA=1 to run db/postgres migrations)."
  exit 0
fi

sql_dir="$ROOT/db/postgres"
if [[ ! -d "$sql_dir" ]]; then
  echo "ERROR: Missing $sql_dir"
  exit 0
fi

# migration id must match INSERT in each file (basename without .sql)
migration_id_from_file() {
  local base
  base="$(basename "$1")"
  echo "${base%.sql}"
}

# Exit 0 if schema_migrations exists and contains this migration id (safe to skip applying the file).
migration_is_recorded() {
  local mid="$1"
  local exists applied
  exists="$(psql "$db_url" -v ON_ERROR_STOP=1 -tAqc \
    "SELECT EXISTS (SELECT 1 FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'schema_migrations');" 2>/dev/null || echo "f")"
  if [[ "$exists" != "t" ]]; then
    return 1
  fi
  applied="$(psql "$db_url" -v ON_ERROR_STOP=1 -tAqc \
    "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE id = '$mid');" 2>/dev/null || echo "f")"
  [[ "$applied" == "t" ]]
}

should_skip_migration_file() {
  local base mid
  base="$(basename "$1")"
  mid="$(migration_id_from_file "$1")"
  if [[ "$base" == *seed* ]] || [[ "$base" == *example* ]] || [[ "$base" == *Seed* ]] || [[ "$base" == *Example* ]]; then
    echo "Skipping $base (seed/example SQL — not a core migration)."
    return 0
  fi
  if migration_is_recorded "$mid"; then
    echo "Skipping $base (already in schema_migrations as $mid)."
    return 0
  fi
  return 1
}

shopt -s nullglob
candidates=("$sql_dir"/*.sql)
shopt -u nullglob
if ((${#candidates[@]} == 0)); then
  echo "WARN: No .sql migrations in $sql_dir"
  exit 0
fi

files=()
while IFS= read -r line; do
  [[ -n "$line" ]] && files+=("$line")
done < <(printf '%s\n' "${candidates[@]}" | LC_ALL=C sort)
if ((${#files[@]} == 0)); then
  files=("${candidates[@]}")
fi

for f in "${files[@]}"; do
  if should_skip_migration_file "$f"; then
    continue
  fi
  echo "Applying $(basename "$f") …"
  psql "$db_url" -v ON_ERROR_STOP=1 -f "$f"
done

if [[ "${GARDENGNOME_DB_APPLY_SEEDS:-0}" == "1" ]]; then
  seeds_dir="$sql_dir/seeds"
  if [[ -d "$seeds_dir" ]]; then
    shopt -s nullglob
    seed_candidates=("$seeds_dir"/*.sql)
    shopt -u nullglob
    seeds=()
    while IFS= read -r line; do
      [[ -n "$line" ]] && seeds+=("$line")
    done < <(printf '%s\n' "${seed_candidates[@]}" | LC_ALL=C sort)
    for s in "${seeds[@]}"; do
      [[ -f "$s" ]] || continue
      echo "Applying seed $(basename "$s") (GARDENGNOME_DB_APPLY_SEEDS=1) …"
      psql "$db_url" -v ON_ERROR_STOP=1 -f "$s"
    done
  else
    echo "WARN: GARDENGNOME_DB_APPLY_SEEDS=1 but $seeds_dir missing."
  fi
fi

echo "PostgreSQL migrations finished (core schema only unless seeds flag was set)."
