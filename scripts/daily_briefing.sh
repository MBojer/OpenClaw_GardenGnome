#!/usr/bin/env bash
# Build daily briefing: load structured weather from DB, ask local Qwen/Ollama for prose, write markdown.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENVF="$ROOT/config/garden.env"
if [[ ! -f "$ENVF" ]]; then
  echo "Missing $ENVF" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
source "$ENVF"
set +a

OUT="${DAILY_BRIEFING_PATH:-$ROOT/briefings/daily.md}"
mkdir -p "$(dirname "$OUT")"
LOG="${DAILY_BRIEFING_LOG:-$ROOT/logs/daily_briefing.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

echo "=== $(date -Iseconds 2>/dev/null || date) daily_briefing ==="

WX="$(mktemp)"
cleanup() { rm -f "$WX"; }
trap cleanup EXIT

psql "${GARDEN_DB_URL}" -v ON_ERROR_STOP=1 -t -A -f "$ROOT/scripts/sql/daily_briefing_weather.sql" >"$WX"
WEATHER_JSON="$(cat "$WX")"

OLLAMA="${OLLAMA_HOST:-http://127.0.0.1:11434}"
MODEL="${BRIEFING_MODEL:-qwen2.5:7b}"

PROMPT="## Current Weather Context
${WEATHER_JSON}

Write a short plain-language garden-oriented weather briefing (2–4 paragraphs). Use SI units; mention frost, spray windows, rain, and wind only if relevant. No JSON."

BODY="$(PROMPT="$PROMPT" MODEL="$MODEL" python3 - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [
        {"role": "system", "content": "You summarise weather for home gardeners. Be concise."},
        {"role": "user", "content": os.environ["PROMPT"]},
    ],
    "stream": False,
}))
PY
)"

set +e
TEXT="$(curl -sS "${OLLAMA}/api/chat" -H "Content-Type: application/json" -d "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',{}).get('content',''))")"
CR=$?
set -e

if [[ "$CR" -ne 0 ]] || [[ -z "$TEXT" ]]; then
  echo "WARN: Ollama chat failed or empty; writing weather JSON only to $OUT"
  {
    echo "# Daily briefing"
    echo
    echo "(LLM unavailable — raw context below)"
    echo
    echo '```json'
    echo "$WEATHER_JSON"
    echo '```'
  } >"$OUT"
  exit 0
fi

{
  echo "# Daily briefing"
  echo
  echo "Generated: $(date -Iseconds 2>/dev/null || date)"
  echo
  echo "$TEXT"
  echo
  echo "---"
  echo
  echo "## Weather context (structured)"
  echo '```json'
  echo "$WEATHER_JSON"
  echo '```'
} >"$OUT"

echo "Wrote $OUT"
