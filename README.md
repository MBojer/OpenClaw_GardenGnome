# OpenClaw_GardenGnome

GardenGnome is a self-hosted OpenClaw agent for home garden management.

This repository is currently **scaffold-only**. Installer, structure, and docs are ready so feature work can start on a stable base.

## Architecture at a glance (scaffold)

```text
[INSTALLER]
  install.sh -> prerequisite checks (+ optional auto-install prompts)
             -> git clone or pull into ~/.openclaw/workspace-gardengnome (default)
             -> .env bootstrap
             -> agent registration (jq-based idempotency)
             -> gateway start/restart so config reloads in the Control UI
             -> optional gateway session bootstrap (so Sessions lists the agent)
             -> cron scaffold step
             -> verification

[PLACEHOLDER AREAS]
  config/  scripts/  db/  skills/
```

## Prerequisites

The installer expects these commands on your `PATH`:

| Tool | Notes |
|------|--------|
| **openclaw** | OpenClaw CLI (install from your OpenClaw distribution or docs; not installed via Homebrew/apt by this script) |
| **jq** | JSON parsing for agent idempotency |
| **git** | Clone / update the workspace checkout |
| **curl** | Used when you run the one-liner |
| **python3** | Cron scaffold and future automation |
| **node** | OpenClaw / tooling expectations |
| **crontab** | User crontab CLI (Debian/Ubuntu: `cron` package; RHEL/Fedora: `cronie`; macOS includes it) |
| **bash** | Installer shell |

Recommended: **Node.js 22+**, **Python 3.10+** (align with your OpenClaw stack).

### Interactive prerequisite help

If you run the installer from a **terminal** (with a usable `/dev/tty`), it will:

1. List anything missing from the table above.
2. Show **copy-paste** install hints for **Homebrew**, **apt**, **dnf**, or **yum** when detected.
3. Optionally run an **automatic** install for **jq, git, curl, python3, node, and cron/crontab** (e.g. `cron` / `cronie`; not `openclaw`) if you answer **y** to the prompt.
4. For **openclaw** only: it will ask you to install it yourself, then **press Enter** to continue once it is on `PATH`.

`curl … | bash` still works in a real terminal because prompts are read from **`/dev/tty`**, not from the script on stdin.

### Non-interactive / CI

Set **`GARDENGNOME_NONINTERACTIVE=1`** or **`CI=true`**, or run where **`/dev/tty`** is unavailable. The installer will print install hints and **exit** if anything is missing (no prompts).

```bash
GARDENGNOME_NONINTERACTIVE=1 curl -fsSL …/install.sh | bash
```

## One-liner install

```bash
curl -fsSL https://raw.githubusercontent.com/MBojer/OpenClaw_GardenGnome/main/install.sh | bash
```

This downloads **only** `install.sh`; that script then **clones or updates** the full repository into the workspace directory (see below). You do **not** need to clone the repo first.

## Where files land (default)

By default the installer uses:

- **`GARDENGNOME_ROOT`**: `$HOME/.openclaw/workspace-gardengnome`

Override if needed:

```bash
export GARDENGNOME_ROOT="$HOME/custom/path"
curl -fsSL https://raw.githubusercontent.com/MBojer/OpenClaw_GardenGnome/main/install.sh | bash
```

Other useful environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GARDENGNOME_ROOT` | `$HOME/.openclaw/workspace-gardengnome` | Install and OpenClaw `--workspace` path |
| `GARDENGNOME_REPO_URL` | `https://github.com/MBojer/OpenClaw_GardenGnome.git` | Git clone URL |
| `GARDENGNOME_REPO_REF` | `main` | Branch or tag to check out |
| `AGENT_NAME` | `gardengnome` | Agent name in OpenClaw |
| `OPENCLAW_MODEL` | `openrouter/stepfun/step-3.5-flash:free` | Model passed to `openclaw agents add` |
| `GARDENGNOME_BOOTSTRAP_SESSION` | `1` | If `1`, runs one `openclaw agent` turn when no gateway session exists yet (uses your model; set `0` to skip) |

## Manual install (from a git checkout)

Useful when developing the installer or using a fork:

```bash
git clone https://github.com/MBojer/OpenClaw_GardenGnome.git
cd OpenClaw_GardenGnome
chmod +x install.sh install/setup_env.sh install/verify.sh
./install.sh
```

Running `./install.sh` from a checkout still **clones or pulls into `GARDENGNOME_ROOT`** by default (it does not assume the current directory is the workspace). Point `GARDENGNOME_REPO_URL` at your fork or a `file://` URL if you need to test unpublished changes.

## What the installer does

1. Ensures **bash** is available, then resolves **prerequisites** (with optional prompts / auto-install as above).
2. **Bootstrap** the workspace: `git clone` into `GARDENGNOME_ROOT`, or **`git pull --ff-only`** if it is already a git worktree. Fails clearly if the directory exists, is **non-empty**, and is **not** a repository.
3. Creates **`.env`** from **`.env.example`** if missing (existing **`.env`** is kept).
4. Runs scaffold **database** placeholder step.
5. Registers the **`AGENT_NAME`** agent with **`openclaw agents add --workspace "$GARDENGNOME_ROOT"`**, skipping registration if **`openclaw agents list --json`** already contains that name (**`jq`**, not `grep`).
6. Ensures the **OpenClaw gateway service** is running (installs/starts if needed, restarts when already running) so agent changes are reflected in the dashboard/Web UI.
7. **Bootstraps a gateway session** for **`AGENT_NAME`** when none exists yet (one `openclaw agent` turn so **Control UI → Sessions** shows `agent:<name>:…`). Skipped when `GARDENGNOME_BOOTSTRAP_SESSION=0` or a session already exists.
8. Runs the **cron** scaffold helper (`install/setup_cron.py`).
9. Runs **`install/verify.sh`**.

Re-running is **idempotent**: safe to run again; `.env` is preserved; agent add is skipped when already registered.

## Updates

- **Git only:** `cd "$GARDENGNOME_ROOT" && git pull --ff-only`
- **Or** re-run the one-liner / `./install.sh` (it will fetch and fast-forward when possible).

Local secrets and ignored files (e.g. **`.env`**) should stay out of git; see **`.gitignore`**.

## First run after install

```bash
openclaw health
openclaw agents list
openclaw gateway call sessions.list --json
openclaw dashboard
```

**Control UI:** registered agents appear under **AI & Agents → Agents**. The **Sessions** list only includes agents after at least one gateway chat run exists; the installer creates that on first install unless you set `GARDENGNOME_BOOTSTRAP_SESSION=0`. In **Chat**, use the agent picker if you still see only the default agent.

Then implement features in `scripts/`, `skills/`, and `db/`.

## Reference

Installer approach follows the JobHunter one-liner pattern:
[OpenClaw_JobHunter one-liner install](https://github.com/MBojer/OpenClaw_JobHunter?tab=readme-ov-file#one-liner-install)
