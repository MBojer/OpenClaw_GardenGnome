#!/usr/bin/env bash
# Install user-level systemd timers for GardenGnome weather jobs (Linux + systemd only).
# Usage: bash scripts/setup_cron.sh [/path/to/GARDENGNOME_ROOT]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping systemd user timers (not on systemd?)."
  exit 0
fi

UNIT_SRC="$ROOT/install/systemd/user"
if [[ ! -d "$UNIT_SRC" ]]; then
  echo "Missing $UNIT_SRC"
  exit 1
fi

USER_UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$USER_UNIT"

for template in "$UNIT_SRC"/*.service "$UNIT_SRC"/*.timer; do
  [[ -f "$template" ]] || continue
  base="$(basename "$template")"
  sed "s|__GARDENGNOME_ROOT__|$ROOT|g" "$template" >"$USER_UNIT/$base"
  echo "Installed $USER_UNIT/$base"
done

systemctl --user daemon-reload
for t in gardengnome-weather-current.timer gardengnome-weather-archive.timer gardengnome-weather-alerts.timer; do
  systemctl --user enable "$t"
  systemctl --user start "$t"
  echo "Enabled and started $t"
done

echo "GardenGnome weather timers are active (user session)."
