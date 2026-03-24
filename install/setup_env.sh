#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

if [[ ! -f ".env.example" ]]; then
  echo "ERROR: .env.example is missing in $ROOT"
  exit 1
fi

if [[ -f ".env" ]]; then
  echo ".env already exists; keeping existing file."
  exit 0
fi

cp ".env.example" ".env"
echo "Created .env from .env.example"
echo "Review and update .env values before production use."
