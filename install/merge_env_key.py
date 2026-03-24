#!/usr/bin/env python3
"""Set or replace KEY="value" in a dotenv file (value double-quoted, escaped)."""
from __future__ import annotations

import pathlib
import re
import sys


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: merge_env_key.py <envfile> <KEY> <value>", file=sys.stderr)
        sys.exit(2)
    path = pathlib.Path(sys.argv[1])
    key, val = sys.argv[2], sys.argv[3]
    esc = val.replace("\\", "\\\\").replace('"', '\\"')
    line = f'{key}="{esc}"\n'
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pat = re.compile("^" + re.escape(key) + r"=.*$", re.MULTILINE)
    if pat.search(text):
        text = pat.sub(line.rstrip("\n"), text, count=1)
        if not text.endswith("\n"):
            text += "\n"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
