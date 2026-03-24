# OpenClaw_GardenGnome

GardenGnome is a self-hosted OpenClaw agent for home garden management.

This repository is currently **scaffold-only**. Installer, structure, and docs are ready so feature work can start on a stable base.

## Architecture at a glance (scaffold)

```text
[INSTALLER]
  install.sh -> prerequisite checks (+ optional auto-install prompts)
             -> git clone or pull into ~/.openclaw/workspace-gardengnome (default)
             -> .env bootstrap + optional GARDENGNOME_DATABASE_URL (prompt / export)
             -> ensure psql on PATH when URL set (hints + optional auto-install)
             -> PostgreSQL connectivity test + optional db/postgres/*.sql
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
| **psql** | **Required when `GARDENGNOME_DATABASE_URL` is set** (connectivity test + applying **`db/postgres/*.sql`** when **`GARDENGNOME_DB_APPLY_SCHEMA=1`**). Not needed if the URL is empty or **`GARDENGNOME_DB_SKIP_INIT=1`**. |

Recommended: **Node.js 22+**, **Python 3.10+** (align with your OpenClaw stack). For applied schema: **PostgreSQL 13+** (uses `gen_random_uuid()`).

### Interactive prerequisite help

If you run the installer from a **terminal** (with a usable `/dev/tty`), it will:

1. List anything missing from the table above.
2. Show **copy-paste** install hints for **Homebrew**, **apt**, **dnf**, or **yum** when detected.
3. Optionally run an **automatic** install for **jq, git, curl, python3, node, and cron/crontab** (e.g. `cron` / `cronie`; not `openclaw`) if you answer **y** to the prompt.
4. For **openclaw** only: it will ask you to install it yourself, then **press Enter** to continue once it is on `PATH`.
5. Optionally asks for **`GARDENGNOME_DATABASE_URL`** (PostgreSQL URL) so the installer can verify connectivity — skip with Enter, or set **`GARDENGNOME_DB_SKIP_INIT=1`** in `.env` to suppress the prompt.
6. If a database URL is configured, offers an **optional automatic install** for the **PostgreSQL client (`psql`)** (same package managers as above) when **`psql`** is missing.

`curl … | bash` still works in a real terminal because prompts are read from **`/dev/tty`**, not from the script on stdin.

Pass a URL non-interactively:

```bash
export GARDENGNOME_DATABASE_URL='postgresql://user:pass@host:5432/gardengnome?sslmode=prefer'
curl -fsSL https://raw.githubusercontent.com/MBojer/OpenClaw_GardenGnome/main/install.sh | bash
```

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
| `GARDENGNOME_DATABASE_URL` | _(empty)_ | **PostgreSQL URL** (`postgresql://…`); if set, the installer runs a connectivity check. Usually stored in `.env` (see `.env.example`) |
| `GARDENGNOME_DB_APPLY_SCHEMA` | `0` | Set `1` to run `db/postgres/*.sql` after a successful connectivity check (needs **`psql`**) |
| `GARDENGNOME_DB_SKIP_INIT` | `0` | Set `1` to skip DB prompt, connectivity test, and schema apply |

## Manual install (from a git checkout)

Useful when developing the installer or using a fork:

```bash
git clone https://github.com/MBojer/OpenClaw_GardenGnome.git
cd OpenClaw_GardenGnome
chmod +x install.sh install/setup_env.sh install/setup_db.sh install/verify.sh
./install.sh
```

Running `./install.sh` from a checkout still **clones or pulls into `GARDENGNOME_ROOT`** by default (it does not assume the current directory is the workspace). Point `GARDENGNOME_REPO_URL` at your fork or a `file://` URL if you need to test unpublished changes.

## What the installer does

1. Ensures **bash** is available, then resolves **prerequisites** (with optional prompts / auto-install as above).
2. **Bootstrap** the workspace: `git clone` into `GARDENGNOME_ROOT`, or **`git pull --ff-only`** if it is already a git worktree. Fails clearly if the directory exists, is **non-empty**, and is **not** a repository.
3. Creates **`.env`** from **`.env.example`** if missing (existing **`.env`** is kept). Merge new keys from **`.env.example`** by hand if you already have a **`.env`** from an older install.
4. Optionally records **`GARDENGNOME_DATABASE_URL`**: interactive prompt (TTY), or **`export`** before install, writes into **`.env`** via **`install/merge_env_key.py`**. Skipped when **`GARDENGNOME_DB_SKIP_INIT=1`** or the URL is already set in **`.env`**.
5. Runs **`install/setup_db.sh`**: if the URL is **unset**, skips DB work; if **set**, runs **`psql "$URL" -c 'SELECT 1'`** (connectivity). If **`GARDENGNOME_DB_APPLY_SCHEMA=1`**, applies **`db/postgres/*.sql`** after a successful check.
6. Registers the **`AGENT_NAME`** agent with **`openclaw agents add --workspace "$GARDENGNOME_ROOT"`**, skipping registration if **`openclaw agents list --json`** already contains that name (**`jq`**, not `grep`).
7. Ensures the **OpenClaw gateway service** is running (installs/starts if needed, restarts when already running) so agent changes are reflected in the dashboard/Web UI.
8. **Bootstraps a gateway session** for **`AGENT_NAME`** when none exists yet (one `openclaw agent` turn so **Control UI → Sessions** shows `agent:<name>:…`). Skipped when `GARDENGNOME_BOOTSTRAP_SESSION=0` or a session already exists.
9. Runs the **cron** scaffold helper (`install/setup_cron.py`).
10. Runs **`install/verify.sh`**.

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

**Database:** Put **`GARDENGNOME_DATABASE_URL`** (e.g. `postgresql://user:pass@host:5432/dbname?sslmode=prefer`) in **`$GARDENGNOME_ROOT/.env`**, or export it before running the installer. Ensure the target database exists. Install **`psql`** to enable the connectivity check; set **`GARDENGNOME_DB_APPLY_SCHEMA=1`** to apply **`db/postgres/*.sql`**. Use **`GARDENGNOME_DB_SKIP_INIT=1`** to skip all DB steps. Re-run **`bash install/setup_db.sh "$GARDENGNOME_ROOT"`** after changing credentials.

Then implement features in `scripts/`, `skills/`, and `db/`.

## Reference

Installer approach follows the JobHunter one-liner pattern:
[OpenClaw_JobHunter one-liner install](https://github.com/MBojer/OpenClaw_JobHunter?tab=readme-ov-file#one-liner-install)
