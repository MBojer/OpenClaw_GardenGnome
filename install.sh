#!/usr/bin/env bash
set -euo pipefail

# Defaults (override with env)
GARDENGNOME_ROOT="${GARDENGNOME_ROOT:-$HOME/.openclaw/workspace-gardengnome}"
GARDENGNOME_REPO_URL="${GARDENGNOME_REPO_URL:-https://github.com/MBojer/OpenClaw_GardenGnome.git}"
GARDENGNOME_REPO_REF="${GARDENGNOME_REPO_REF:-main}"
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

# Read a line from the controlling terminal so `curl … | bash` can still prompt.
read_tty() {
  local prompt=$1
  local var=$2
  if [[ -r /dev/tty ]]; then
    read -r -p "$prompt" "$var" < /dev/tty
  else
    read -r -p "$prompt" "$var"
  fi
}

is_interactive_install() {
  [[ "${GARDENGNOME_NONINTERACTIVE:-}" != "1" && "${CI:-}" != "true" ]] || return 1
  [[ -r /dev/tty && -w /dev/tty ]] || return 1
  return 0
}

detect_pkg_installer() {
  if command -v brew >/dev/null 2>&1; then
    echo brew
  elif command -v apt-get >/dev/null 2>&1; then
    echo apt
  elif command -v dnf >/dev/null 2>&1; then
    echo dnf
  elif command -v yum >/dev/null 2>&1; then
    echo yum
  else
    echo none
  fi
}

print_manual_install_hints() {
  echo ""
  echo "Install hints (run outside this script if needed):"
  local pm
  pm="$(detect_pkg_installer)"
  case "$pm" in
    brew)
      echo "  brew install jq git curl python node"
      echo "  # crontab: included with macOS (install cron/cronie on Linux if missing)."
      echo "  # OpenClaw CLI: install per your OpenClaw / OpenClaw docs (not on default Homebrew)."
      ;;
    apt)
      echo "  sudo apt-get update && sudo apt-get install -y jq git curl python3 nodejs npm cron"
      echo "  # OpenClaw CLI: install from project documentation."
      ;;
    dnf | yum)
      echo "  sudo $pm install -y jq git curl python3 nodejs cronie"
      echo "  # OpenClaw CLI: install from project documentation."
      ;;
    *)
      echo "  Install: jq, git, curl, Python 3, Node.js, crontab (e.g. apt: cron, dnf: cronie), and the OpenClaw CLI, then rerun."
      ;;
  esac
  echo ""
}

run_auto_pkg_install() {
  local pm
  pm="$(detect_pkg_installer)"
  case "$pm" in
    brew)
      brew install jq git curl python node
      ;;
    apt)
      sudo apt-get update -qq
      sudo apt-get install -y jq git curl python3 nodejs npm cron
      ;;
    dnf)
      sudo dnf install -y jq git curl python3 nodejs cronie
      ;;
    yum)
      sudo yum install -y jq git curl python3 nodejs cronie
      ;;
    *)
      echo "ERROR: No supported package manager (brew, apt-get, dnf, or yum) found."
      return 1
      ;;
  esac
}

missing_from_list() {
  local miss=()
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || miss+=("$c")
  done
  if ((${#miss[@]})); then
    printf '%s\n' "${miss[@]}"
  fi
}

ensure_prerequisites() {
  local need=(openclaw jq git curl python3 node crontab)
  local miss
  miss="$(missing_from_list "${need[@]}")"
  [[ -z "$miss" ]] && return 0

  echo "The following required commands are not on PATH:"
  sed 's/^/  - /' <<< "$miss"

  if is_interactive_install; then
    local ans
    print_manual_install_hints
    read_tty "Try automatic install for jq, git, curl, python3, node, and cron/crontab (where supported)? [y/N] " ans
    case "${ans}" in
      y | Y | yes | YES | Yes)
        if run_auto_pkg_install; then
          :
        else
          echo "Automatic install failed or is unavailable."
        fi
        ;;
    esac
  else
    print_manual_install_hints
    echo "Non-interactive session (piped input, no /dev/tty, CI, or GARDENGNOME_NONINTERACTIVE=1)."
    echo "Install the tools above, then rerun."
    exit 1
  fi

  miss="$(missing_from_list "${need[@]}")"
  # Everything except openclaw must be present before the openclaw-specific prompt
  local still=""
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" == openclaw ]] && continue
    [[ -z "$line" ]] && continue
    still+="${line}"$'\n'
  done <<< "$miss"
  if [[ -n "$still" ]]; then
    echo "ERROR: Still missing after install attempt:"
    sed 's/^/  - /' <<< "$still"
    exit 1
  fi

  if ! command -v openclaw >/dev/null 2>&1; then
    echo ""
    echo "OpenClaw CLI (openclaw) is still required and is not installed by this script."
    print_manual_install_hints
    if is_interactive_install; then
      local _
      read_tty "Install openclaw, then press Enter to continue (or Ctrl+C to abort) … " _
    else
      exit 1
    fi
    if ! command -v openclaw >/dev/null 2>&1; then
      echo "ERROR: openclaw still not found on PATH."
      exit 1
    fi
  fi

  require_cmd jq
  require_cmd git
  require_cmd curl
  require_cmd python3
  require_cmd node
  require_cmd crontab
}

dir_empty() {
  [ -d "$1" ] && [ -z "$(ls -A "$1" 2>/dev/null || true)" ]
}

agent_already_registered() {
  local json
  json="$(openclaw agents list --json 2>/dev/null)" || return 1
  echo "$json" | jq -e --arg n "$AGENT_NAME" '
    (if type == "array" then . else (.agents // []) end)
    | map(select((.name // .id) == $n))
    | length > 0
  ' >/dev/null 2>&1
}

agent_has_gateway_session() {
  local json
  json="$(openclaw gateway call sessions.list --json 2>/dev/null)" || return 1
  echo "$json" | jq -e --arg id "$AGENT_NAME" '
    (.sessions // [])
    | map(.key // "")
    | any(startswith("agent:" + $id + ":"))
  ' >/dev/null 2>&1
}

maybe_bootstrap_agent_session() {
  [[ "${GARDENGNOME_BOOTSTRAP_SESSION:-1}" == "0" ]] && {
    echo "GARDENGNOME_BOOTSTRAP_SESSION=0 — skipping gateway session bootstrap."
    return 0
  }

  if agent_has_gateway_session; then
    echo "Gateway session for '$AGENT_NAME' already exists; skipping bootstrap."
    return 0
  fi

  echo "No gateway session yet for '$AGENT_NAME'. Running one bootstrap turn via the Gateway"
  echo "(so Control UI → Sessions lists this agent). Set GARDENGNOME_BOOTSTRAP_SESSION=0 to skip."

  if openclaw agent --agent "$AGENT_NAME" \
    --message "GardenGnome install bootstrap. Reply with exactly: HEARTBEAT_OK" \
    --json >/dev/null 2>&1; then
    echo "Bootstrap complete."
  else
    echo "WARN: Bootstrap run failed (model credentials or gateway). When ready, run:"
    echo "  openclaw agent --agent $AGENT_NAME --message 'Hello' --json"
  fi
}

gateway_rpc_healthy() {
  openclaw gateway health >/dev/null 2>&1
}

ensure_gateway_running() {
  # Prefer service-managed gateway so agent state is visible in dashboard/web UI.
  if gateway_rpc_healthy; then
    openclaw gateway restart >/dev/null 2>&1 || true
    return 0
  fi

  if openclaw gateway status >/dev/null 2>&1; then
    openclaw gateway start >/dev/null 2>&1 || true
  else
    openclaw gateway install >/dev/null 2>&1 || true
    openclaw gateway start >/dev/null 2>&1 || true
  fi

  gateway_rpc_healthy
}

step "GardenGnome installer — prerequisites"
require_cmd bash
ensure_prerequisites
echo "Prerequisites OK."

step "GardenGnome installer — bootstrap repository"
TARGET="$GARDENGNOME_ROOT"
mkdir -p "$(dirname "$TARGET")"

if [ -d "$TARGET" ] && git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Updating existing checkout: $TARGET"
  git -C "$TARGET" fetch origin
  git -C "$TARGET" checkout "$GARDENGNOME_REPO_REF"
  if ! git -C "$TARGET" pull --ff-only; then
    echo "ERROR: git pull --ff-only failed in $TARGET."
    echo "Resolve divergent commits (stash, merge, or reset), then rerun."
    exit 1
  fi
elif [ ! -e "$TARGET" ]; then
  echo "Cloning into $TARGET"
  git clone --depth 1 -b "$GARDENGNOME_REPO_REF" "$GARDENGNOME_REPO_URL" "$TARGET"
elif dir_empty "$TARGET"; then
  echo "Cloning into empty directory $TARGET"
  git clone --depth 1 -b "$GARDENGNOME_REPO_REF" "$GARDENGNOME_REPO_URL" "$TARGET"
else
  echo "ERROR: $TARGET exists, is not empty, and is not a git repository."
  echo "Set GARDENGNOME_ROOT to another path or move/rename the directory."
  exit 1
fi

ROOT="$(cd "$TARGET" && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/.env.example" ]]; then
  echo "ERROR: .env.example missing in $ROOT (bootstrap may be corrupt)."
  exit 1
fi

echo "Repository root: $ROOT"

step "1/8 Setup environment"
bash "$ROOT/install/setup_env.sh" "$ROOT"

step "2/8 Database migration placeholder"
echo "Scaffold phase: no database migrations to run yet."

step "3/8 Register OpenClaw agent"
agent_was_added=0
if agent_already_registered; then
  echo "Agent '$AGENT_NAME' already registered; skipping."
else
  openclaw agents add "$AGENT_NAME" \
    --workspace "$ROOT" \
    --model "$MODEL_DEFAULT" \
    --non-interactive \
    --json
  echo "Agent '$AGENT_NAME' registered."
  agent_was_added=1
fi

step "4/8 Ensure OpenClaw gateway is running"
if ensure_gateway_running; then
  if [[ "$agent_was_added" -eq 1 ]]; then
    echo "Gateway is running and reloaded for new agent visibility."
  else
    echo "Gateway is running."
  fi
else
  echo "WARN: Could not verify a running OpenClaw gateway."
  echo "      Run: openclaw gateway install && openclaw gateway start"
  echo "      Then check: openclaw gateway status"
fi

step "5/8 Bootstrap Control UI session"
if gateway_rpc_healthy; then
  maybe_bootstrap_agent_session
else
  echo "WARN: Gateway not healthy; cannot bootstrap session yet."
fi

step "6/8 Setup cron scaffolding"
python3 "$ROOT/install/setup_cron.py"

step "7/8 Verify installation"
bash "$ROOT/install/verify.sh" "$ROOT"

step "8/8 Done"
echo ""
echo "GardenGnome installation complete."
echo "Next steps:"
echo "  1) Edit .env values in $ROOT"
echo "  2) Run: openclaw health"
echo "  3) Open dashboard with: openclaw dashboard"
echo "  4) In Chat, use the agent picker if you still see only the default agent (main)."
echo "  5) Update with: cd $ROOT && git pull --ff-only  (or rerun this installer)"
