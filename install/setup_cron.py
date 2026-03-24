#!/usr/bin/env python3
"""
Scaffold cron setup for GardenGnome.
Safe no-op if cron tool is unavailable.
"""

from __future__ import annotations

import shutil
import sys


def main() -> int:
    if shutil.which("crontab") is None:
        print("WARN: crontab not found; skipping cron registration.")
        return 0

    print("Cron scaffold step complete.")
    print("No scheduled jobs are installed yet in scaffold phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
