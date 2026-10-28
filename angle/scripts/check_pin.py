#!/usr/bin/env python3
"""Validates angle/pin.toml and angle/bundles.toml.

    check_pin.py [--allow-unpublished] [angle-dir]

Fails on a missing key or platform, a malformed commit, version or digest, a
URL outside the release named by bundles.toml's bundle_version, or (unless
--allow-unpublished) a platform without a published URL and digest.
angle-dir defaults to this repository's angle/.
"""

import re
import sys
import tomllib
from pathlib import Path

PLATFORMS = ("linux-x64", "macos-arm64", "windows-x64")
VERSION = r"angle-\d+\.\d+"


def pin_problems(pin: dict) -> list[str]:
    found = []
    for key in ("angle_commit", "depot_tools_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(pin.get(key, ""))):
            found.append(f"{key} must be a 40-character lowercase hex commit")
    if not re.fullmatch(VERSION, str(pin.get("bundle_version", ""))):
        found.append("bundle_version must look like angle-<branch>.<n>")
    return found


def bundles_problems(bundles: dict, allow_unpublished: bool) -> list[str]:
    found = []
    version = str(bundles.get("bundle_version", ""))
    if not re.fullmatch(VERSION, version):
        found.append("bundle_version must look like angle-<branch>.<n>")
        version = ""
    platforms = bundles.get("platform", {})
    for name in PLATFORMS:
        entry = platforms.get(name)
        if entry is None:
            found.append(f"missing [platform.{name}]")
            continue
        url, sha = entry.get("url", ""), entry.get("sha256", "")
        if not url and not sha and allow_unpublished:
            continue
        if not str(url).startswith("https://"):
            found.append(f"platform.{name}.url must be an https URL")
        elif version and f"/download/{version}/" not in str(url):
            found.append(f"platform.{name}.url is not in the {version} release")
        if not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
            found.append(f"platform.{name}.sha256 must be 64 lowercase hex characters")
    return found


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    angle = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    allow_unpublished = "--allow-unpublished" in sys.argv
    failed = False
    for name, check in (
        ("pin.toml", pin_problems),
        ("bundles.toml", lambda data: bundles_problems(data, allow_unpublished)),
    ):
        path = angle / name
        with open(path, "rb") as f:
            found = check(tomllib.load(f))
        if found:
            failed = True
            print(f"{path}:\n  " + "\n  ".join(found), file=sys.stderr)
        else:
            print(f"{path}: ok")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
