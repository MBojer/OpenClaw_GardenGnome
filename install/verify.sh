#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

echo "Running scaffold verification..."

missing=0
for required in "README.md" "install.sh" ".env.example" "install/setup_env.sh" "install/setup_db.sh" "install/merge_env_key.py" "install/setup_cron.py" "db/postgres/001_schema_placeholder.sql"; do
  if [[ ! -f "$required" ]]; then
    echo "ERROR: Missing required file: $required"
    missing=1
  fi
done

for cmd in python3 node jq git curl crontab; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "WARN: Command not found: $cmd"
  fi
done

if ! command -v openclaw >/dev/null 2>&1; then
  echo "WARN: openclaw CLI not found (required for agent registration)."
fi

if [[ $missing -ne 0 ]]; then
  exit 1
fi

echo "Scaffold verification finished."
