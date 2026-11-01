#!/usr/bin/env bash
# Succeeds when <bump> changes nothing but angle/pin.toml since it left <base>,
# that is, when no fix was pushed on top of an angle-bump.yml bump:
# pin_only.sh <base> <bump>
set -euo pipefail
[ "$(git diff --no-renames --name-only "$1...$2")" = angle/pin.toml ]
