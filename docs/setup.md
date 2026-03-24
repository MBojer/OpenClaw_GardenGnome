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
- Agent not listed: run `openclaw agents list` and re-run `./install.sh`.
