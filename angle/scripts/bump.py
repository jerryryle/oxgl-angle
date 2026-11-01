#!/usr/bin/env python3
"""Pins angle/pin.toml to the ANGLE commit Chrome stable ships.

    bump.py [angle-dir]

Reads the current Linux Chrome stable version, takes `angle_revision` from that
version's Chromium DEPS, and, when it differs from the pinned commit, rewrites
`angle_commit`, `chromium_branch` and `bundle_version` (`angle-<branch>.1` for a
new branch, `.<n+1>` for a new commit on the pinned one). Prints the new
bundle_version, or nothing when the pin is current. angle-dir defaults to this
repository's angle/.
"""

import base64
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

STABLE = (
    "https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions"
    "?pageSize=1"
)
DEPS = "https://chromium.googlesource.com/chromium/src/+/refs/tags/{}/DEPS?format=TEXT"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def stable_version() -> str:
    version = json.loads(fetch(STABLE))["versions"][0]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise SystemExit(f"unexpected Chrome version {version!r}")
    return version


def angle_revision(version: str) -> str:
    deps = base64.b64decode(fetch(DEPS.format(version))).decode()
    match = re.search(r"'angle_revision':\s*'([0-9a-f]{40})'", deps)
    if not match:
        raise SystemExit(f"angle_revision not found in Chromium {version} DEPS")
    return match.group(1)


def next_bundle_version(current: str, branch: int) -> str:
    match = re.fullmatch(r"angle-(\d+)\.(\d+)", current)
    if not match:
        raise SystemExit(f"malformed bundle_version {current!r}")
    if int(match.group(1)) == branch:
        return f"angle-{branch}.{int(match.group(2)) + 1}"
    return f"angle-{branch}.1"


def set_value(text: str, key: str, value: str, comment: str | None = None) -> str:
    line = f'{key} = "{value}"'
    if comment:
        line = f"{line}  # {comment}"
    text, count = re.subn(rf"^{key}\s*=.*$", line, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"{key} not found in pin.toml")
    return text


def main() -> None:
    args = sys.argv[1:]
    path = (Path(args[0]) if args else Path(__file__).resolve().parents[1]) / "pin.toml"
    text = path.read_text()
    pin = tomllib.loads(text)
    version = stable_version()
    major, branch = version.split(".")[0], int(version.split(".")[2])
    pinned_branch = int(pin["bundle_version"].removeprefix("angle-").split(".")[0])
    commit = angle_revision(version)
    # Stable occasionally rolls back to an older branch; never follow it there.
    if commit == pin["angle_commit"] or branch < pinned_branch:
        print(f"pin is current for Chrome {version}", file=sys.stderr)
        return
    bundle_version = next_bundle_version(pin["bundle_version"], branch)
    text = set_value(text, "angle_commit", commit)
    text = set_value(
        text, "chromium_branch", f"chromium/{branch}", f"Chrome {major} stable; informational"
    )
    text = set_value(
        text,
        "bundle_version",
        bundle_version,
        "release tag; .N increments on rebuilds of the same branch",
    )
    path.write_text(text)
    print(f"Chrome {version}: ANGLE {commit} as {bundle_version}", file=sys.stderr)
    print(bundle_version)


if __name__ == "__main__":
    main()
