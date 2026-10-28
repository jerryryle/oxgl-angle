#!/usr/bin/env bash
# Reads a top-level string value from angle/pin.toml: pin.sh <key>
set -euo pipefail
key="$1"
pin="$(dirname "$0")/../pin.toml"
sed -n "s/^${key}[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$pin" | head -n1
