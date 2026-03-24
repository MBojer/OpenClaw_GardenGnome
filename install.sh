#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

AGENT_NAME="${AGENT_NAME:-gardengnome}"
MODEL_DEFAULT="${OPENCLAW_MODEL:-openrouter/stepfun/step-3.5-flash:free}"

step() {
  echo ""
  echo "==> $1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $1"
    exit 1
  fi
}

step "GardenGnome scaffold installer"
echo "Repository root: $ROOT"

step "1/6 Check prerequisites"
require_cmd bash
require_cmd python3
require_cmd node
require_cmd curl

if ! command -v openclaw >/dev/null 2>&1; then
  echo "ERROR: openclaw CLI is required. Install it and rerun."
  exit 1
fi
echo "Prerequisites OK."

step "2/6 Setup environment"
bash "$ROOT/install/setup_env.sh" "$ROOT"

step "3/6 Database migration placeholder"
echo "Scaffold phase: no database migrations to run yet."

step "4/6 Register OpenClaw agent"
if openclaw agents list --json 2>/dev/null | grep -q "\"$AGENT_NAME\""; then
  echo "Agent '$AGENT_NAME' already registered; skipping."
else
  openclaw agents add "$AGENT_NAME" \
    --workspace "$ROOT" \
    --model "$MODEL_DEFAULT" \
    --non-interactive \
    --json
  echo "Agent '$AGENT_NAME' registered."
fi

step "5/6 Setup cron scaffolding"
python3 "$ROOT/install/setup_cron.py"

step "6/6 Verify installation"
bash "$ROOT/install/verify.sh" "$ROOT"

echo ""
echo "GardenGnome scaffold installation complete."
echo "Next steps:"
echo "  1) Edit .env values"
echo "  2) Run: openclaw health"
echo "  3) Start feature development in scripts/ and skills/"
