# Setup Notes

## Local development

1. Clone repository.
2. Run `./install.sh`.
3. Fill `.env` values for your environment.
4. Validate with `openclaw health`.

## Re-running installer safely

- `.env` is not overwritten if it already exists.
- Existing agent registration is detected and skipped.
- Cron step is scaffold-only (no real schedules yet).
- Verification can be run directly with `bash install/verify.sh`.

## Troubleshooting

- `openclaw: command not found`: install OpenClaw CLI and rerun.
- `node` or `python3` missing: install required runtime and rerun.
- Agent missing from **`openclaw agents list`**: re-run `./install.sh` or run `openclaw agents add` with the same `--workspace` as `GARDENGNOME_ROOT`.
- Agent in CLI / **Agents** tab but not under **Sessions** in the Control UI: the UI session list is empty until a gateway session exists. Run `./install.sh` (it bootstraps one turn when needed), or manually: `openclaw agent --agent gardengnome --message "Hello" --json`. To skip the automatic bootstrap turn, set `GARDENGNOME_BOOTSTRAP_SESSION=0`.
- Chat only talks to **main**: use the Control UI **Chat** agent picker and choose `gardengnome` (or your `AGENT_NAME`).
