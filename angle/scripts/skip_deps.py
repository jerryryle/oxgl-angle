#!/usr/bin/env python3
"""Tells gclient not to fetch DEPS entries the bundle build never uses.

    skip_deps.py <angle-checkout>

Run after scripts/bootstrap.py writes .gclient and before `gclient sync`.
third_party/clang-format/script is formatter tooling no GN target references;
its pinned commit at chromium/8078 is no longer served by the
chromium.googlesource.com mirror, so fetching it fails the whole sync.

On Linux, bootstrap.py also adds a `target_os` line naming android, which makes
gclient fetch the Android SDK, NDK, JDK, emulator and build tools, several GB
the Linux bundles never use. That filled the CI runners' disks mid-sync, so
that line is dropped.
"""

import re
import sys
from pathlib import Path

SKIPPED = ("third_party/clang-format/script",)
ANCHOR = '"custom_deps" : {'
ANDROID_TARGET = re.compile(r"^target_os\s*=.*android.*\n?", re.MULTILINE)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: skip_deps.py <angle-checkout>")
    gclient = Path(sys.argv[1]) / ".gclient"
    text = gclient.read_text()
    if text.count(ANCHOR) != 1:
        sys.exit(f"skip_deps: expected one {ANCHOR!r} in {gclient}")
    entries = "".join(f'\n      "{dep}": None,' for dep in SKIPPED if f'"{dep}"' not in text)
    text = ANDROID_TARGET.sub("", text.replace(ANCHOR, ANCHOR + entries))
    gclient.write_text(text)


if __name__ == "__main__":
    main()
