# OpenClaw_GardenGnome

GardenGnome is a self-hosted OpenClaw agent for home garden management.

This repository is currently **scaffold-only**. Installer, structure, and docs are ready so feature work can start on a stable base.

## Architecture at a glance (scaffold)

```text
[INSTALLER]
  install.sh -> prerequisite checks
             -> .env bootstrap
             -> agent registration
             -> cron scaffold step
             -> verification

[PLACEHOLDER AREAS]
  config/  scripts/  db/  skills/
```

## Prerequisites

- OpenClaw CLI installed
- Node.js 22+
- Python 3.10+
- Bash + curl

## One-liner install

```bash
curl -fsSL https://raw.githubusercontent.com/MBojer/OpenClaw_GardenGnome/main/install.sh | bash
```

## Manual install

```bash
git clone https://github.com/MBojer/OpenClaw_GardenGnome.git /home/openclaw/OpenClaw_GardenGnome
cd /home/openclaw/OpenClaw_GardenGnome
chmod +x install.sh install/setup_env.sh install/verify.sh
./install.sh
```

## What the installer does

1. Checks required commands (`python3`, `node`, `curl`, `openclaw`)
2. Creates `.env` from `.env.example` if missing
3. Runs scaffold DB placeholder step
4. Registers `gardengnome` agent (idempotent check first)
5. Runs cron scaffold helper
6. Runs verification checks

Re-running is safe for scaffold setup.

## First run

After installation:

```bash
openclaw health
openclaw agents list
```

Then start implementing features in `scripts/`, `skills/`, and `db/`.

## Reference

Installer approach follows the JobHunter one-liner pattern:
[OpenClaw_JobHunter one-liner install](https://github.com/MBojer/OpenClaw_JobHunter?tab=readme-ov-file#one-liner-install)
