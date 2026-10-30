#!/usr/bin/env python3
"""Validates angle/pin.toml.

    check_pin.py [angle-dir]

Fails on a missing key or a malformed commit or bundle version. angle-dir
defaults to this repository's angle/.
"""

import re
import sys
import tomllib
from pathlib import Path

VERSION = r"angle-\d+\.\d+"


def pin_problems(pin: dict) -> list[str]:
    found = []
    for key in ("angle_commit", "depot_tools_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(pin.get(key, ""))):
            found.append(f"{key} must be a 40-character lowercase hex commit")
    if not re.fullmatch(VERSION, str(pin.get("bundle_version", ""))):
        found.append("bundle_version must look like angle-<branch>.<n>")
    return found


def main() -> None:
    args = sys.argv[1:]
    path = (Path(args[0]) if args else Path(__file__).resolve().parents[1]) / "pin.toml"
    with open(path, "rb") as f:
        found = pin_problems(tomllib.load(f))
    if found:
        print(f"{path}:\n  " + "\n  ".join(found), file=sys.stderr)
        sys.exit(1)
    print(f"{path}: ok")


if __name__ == "__main__":
    main()
