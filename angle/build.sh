#!/usr/bin/env bash
# Builds the oxgl ANGLE bundle for one platform from the revision in pin.toml.
#
#   angle/build.sh fetch            check out depot_tools and ANGLE at the pin
#   angle/build.sh build <platform> configure (gn) and compile (ninja)
#   angle/build.sh bundle <platform> assemble, check and archive the bundle
#   angle/build.sh all <platform>   all of the above
#
# <platform> is linux-x64, linux-arm64 or macos-arm64 (Windows uses build.ps1).
# linux-arm64 is cross-compiled on a Linux x64 host against Chromium's arm64
# sysroot.
# Work happens in $OXGL_ANGLE_WORK (default ~/.cache/oxgl/angle-build), outside
# the repository; output lands in $OXGL_ANGLE_WORK/dist.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
work="${OXGL_ANGLE_WORK:-$HOME/.cache/oxgl/angle-build}"
angle_commit="$("$here/scripts/pin.sh" angle_commit)"
depot_tools_commit="$("$here/scripts/pin.sh" depot_tools_commit)"
bundle_version="$("$here/scripts/pin.sh" bundle_version)"

export PATH="$work/depot_tools:$PATH"
export DEPOT_TOOLS_UPDATE=0          # keep depot_tools at the pinned commit
export DEPOT_TOOLS_WIN_TOOLCHAIN=0   # use the locally installed Visual Studio
if [[ "$(uname -s)" == Darwin && -d /Applications/Xcode.app ]]; then
  # ANGLE needs the full Xcode SDK; select it for this build only.
  export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
fi

fetch() {
  mkdir -p "$work"
  if [[ ! -d "$work/depot_tools" ]]; then
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools "$work/depot_tools"
  fi
  git -C "$work/depot_tools" fetch --quiet origin
  git -C "$work/depot_tools" checkout --quiet "$depot_tools_commit"
  "$work/depot_tools/ensure_bootstrap"   # normally done by self-update, which is disabled

  # Only the pinned commit is needed, so fetch it alone rather than all history.
  if [[ ! -d "$work/angle/.git" ]]; then
    git init --quiet "$work/angle"
    git -C "$work/angle" remote add origin https://chromium.googlesource.com/angle/angle
  fi
  git -C "$work/angle" fetch --quiet --depth 1 origin "$angle_commit"
  git -C "$work/angle" checkout --quiet --force "$angle_commit"
  (cd "$work/angle" && python3 scripts/bootstrap.py && gclient sync -D --force --no-history --jobs 16)
}

out_dir() { echo "$work/angle/out/oxgl-$1"; }

build() {
  local platform="$1" out
  out="$(out_dir "$platform")"
  mkdir -p "$out"
  if [[ "$platform" == linux-arm64 ]]; then
    # ANGLE's DEPS hooks install only the x86/x64 sysroots; fetch the arm64 one
    # (pinned by build/linux/sysroot_scripts/sysroots.json) ourselves.
    (cd "$work/angle" && python3 build/linux/sysroot_scripts/install-sysroot.py --arch=arm64)
  fi
  cat "$here/args/common.gn" "$here/args/$platform.gn" > "$out/args.gn"
  (cd "$work/angle" && gn gen "$out")
  python3 "$here/scripts/bundle.py" --preflight "$platform" "$out" "$work/angle"
  (cd "$work/angle" && autoninja -C "$out" $(cat "$here/args/targets.txt"))
}

bundle() {
  python3 "$here/scripts/bundle.py" "$1" "$(out_dir "$1")" "$work/angle" "$work/dist" "$bundle_version" "$angle_commit"
}

# Network fetches occasionally fail transiently (dropped connections to
# googlesource or Google Storage). Every fetch step is safe to repeat, so retry
# the whole fetch a few times. Each attempt is a separate process so `set -e`
# still stops it at the first failing command.
fetch_with_retry() {
  local attempt delay
  for attempt in 1 2 3; do
    if "$0" fetch-once; then
      return 0
    fi
    [[ $attempt == 3 ]] && break
    delay=$((attempt * 30))
    echo "fetch attempt $attempt failed; retrying in ${delay}s" >&2
    sleep "$delay"
  done
  echo "fetch failed after 3 attempts" >&2
  return 1
}

cmd="${1:-}"
case "$cmd" in
  fetch) fetch_with_retry ;;
  fetch-once) fetch ;;
  build) build "${2:?platform}" ;;
  bundle) bundle "${2:?platform}" ;;
  all) fetch_with_retry; build "${2:?platform}"; bundle "$2" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
