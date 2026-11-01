#!/usr/bin/env python3
"""Pins angle/pin.toml to the ANGLE commit Chrome stable ships.

    bump.py [angle-dir [chrome-version]]

Reads the current Linux Chrome stable version (or uses chrome-version, which
must be a Linux Chrome stable release, current or past), takes
`angle_revision` from that version's Chromium DEPS, and, when it is newer than
the pinned commit, rewrites `angle_commit`, `chromium_branch` and
`bundle_version` (`angle-<branch>.1` for a new branch, `.<n+1>` for a newer
commit on the pinned one). Never moves the pin back: to an older branch, or to
an ancestor of the pinned commit when stable rolls back on the same branch.
Prints the new bundle_version and the Chrome version, or nothing when the pin is
current. angle-dir defaults to this repository's angle/.
"""

import base64
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

STABLE = "https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions"
DEPS = "https://chromium.googlesource.com/chromium/src/+/refs/tags/{}/DEPS?format=TEXT"
# Commits reachable from the second commit but not the first, at most one.
LOG = "https://chromium.googlesource.com/angle/angle/+log/{}..{}?format=JSON&n=1"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def checked_version(version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise SystemExit(f"unexpected Chrome version {version!r}")
    return version


def stable_version() -> str:
    return checked_version(json.loads(fetch(f"{STABLE}?pageSize=1"))["versions"][0]["version"])


def stable_release(version: str) -> str:
    if not json.loads(fetch(f"{STABLE}?filter=version={checked_version(version)}"))["versions"]:
        raise SystemExit(f"Chrome {version} is not a Linux stable release")
    return version


def angle_revision(version: str) -> str:
    deps = base64.b64decode(fetch(DEPS.format(version))).decode()
    match = re.search(r"'angle_revision':\s*'([0-9a-f]{40})'", deps)
    if not match:
        raise SystemExit(f"angle_revision not found in Chromium {version} DEPS")
    return match.group(1)


def has_new_commits(pinned: str, commit: str) -> bool:
    # Gitiles prefixes JSON with )]}' to stop it being run as a script.
    body = fetch(LOG.format(pinned, commit)).decode().removeprefix(")]}'")
    return bool(json.loads(body)["log"])


def parse_bundle_version(version: str) -> tuple[int, int]:
    match = re.fullmatch(r"angle-(\d+)\.(\d+)", version)
    if not match:
        raise SystemExit(f"malformed bundle_version {version!r}")
    return int(match.group(1)), int(match.group(2))


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
    version = stable_release(args[1]) if len(args) > 1 else stable_version()
    major, branch = version.split(".")[0], int(version.split(".")[2])
    pinned_branch, rebuild = parse_bundle_version(pin["bundle_version"])
    commit = angle_revision(version)
    # Stable occasionally rolls back, to an older branch or to an older build
    # on the pinned one; never follow it there.
    if (
        commit == pin["angle_commit"]
        or branch < pinned_branch
        or not has_new_commits(pin["angle_commit"], commit)
    ):
        print(f"pin is current for Chrome {version}", file=sys.stderr)
        return
    rebuild = rebuild + 1 if branch == pinned_branch else 1
    bundle_version = f"angle-{branch}.{rebuild}"
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
    print(bundle_version, version)


if __name__ == "__main__":
    main()
