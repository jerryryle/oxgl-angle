# ANGLE bundle recipe

oxgl renders through [ANGLE](https://chromium.googlesource.com/angle/angle),
with SwiftShader as the software fallback. Google publishes no ANGLE binaries,
so this repository builds them from a pinned revision and publishes them as
release assets. oxgl downloads those bundles and verifies them against the
digests in its `angle/bundles.toml`, so ANGLE is built only when its recipe
changes.

Bundles are built for five platforms: `linux-x64`, `linux-arm64`,
`macos-arm64`, `windows-x64` and `windows-arm64`. The arm64 Linux and Windows
bundles are cross-compiled on x64 hosts, as Chromium does, and smoke-tested on
arm64 runners.

## Files

| File | Purpose |
|---|---|
| `pin.toml` | Recipe inputs: ANGLE commit, depot_tools commit, `bundle_version` (release tag) |
| `args/*.gn` | GN build arguments: `common.gn` plus one file per platform |
| `args/targets.txt` | Ninja targets to build |
| `build.sh`, `build.ps1` | Build recipe (`fetch`, `build`, `bundle`, `all`) for macOS/Linux and Windows (x64 and arm64) |
| `scripts/bundle.py` | Assembles the bundle and enforces the outcome checks |
| `scripts/check_pin.py` | Validates `pin.toml` |
| `licenses.toml` | SPDX licenses for third_party directories lacking `README.chromium` metadata |
| `smoke/smoke.c` | Loads a bundle, renders one frame with SwiftShader, reads a pixel back |
| `../deny.toml` | The license allowlist, a copy of oxgl's (which is authoritative) |

## Bundle layout

```
lib/        libEGL, libGLESv2, SwiftShader Vulkan ICD + vk_swiftshader_icd.json (stripped)
include/    EGL, GLES2, GLES3, KHR headers, including ANGLE extension headers
licenses/   license texts of ANGLE and every linked third_party component
BUILD_INFO.json   commit, GN args, toolchain, components with SPDX licenses, file digests
```

Bundles are `angle-<platform>.tar.xz`; unstripped libraries are in
`angle-<platform>-symbols.tar.xz`.

`bundle.py` fails the build if a required library or the ICD manifest is
missing, a required backend is not enabled, a linked component's license is
missing or not on the allowlist in `deny.toml`, or (Linux) a library links
X11/xcb/Wayland or needs glibc newer than 2.31. On Linux arm64 it also fails
if any library has a `LOAD` segment aligned below 64 KiB: arm64 kernels use 4,
16 or 64 KiB pages, and only 64 KiB alignment loads under all of them. The
smallest alignment is recorded in `BUILD_INFO.json` as `min_load_align`.
The GN-arg and license checks also run right after `gn gen`
(`bundle.py --preflight`), so they fail before the compile rather than after it.

`deny.toml` here is a copy of oxgl's allowlist. oxgl's build re-checks every
pinned bundle's component licenses against its own `deny.toml`, so a license
allowed here but not there fails oxgl's build; keep the two in step.

## Building locally

Needs Git, Python 3.11+, and the platform toolchain: on macOS, full Xcode plus
its Metal Toolchain component (`xcodebuild -downloadComponent MetalToolchain`);
on Windows, Visual Studio 2022 with the Windows SDK, plus its ARM64 build tools
for `windows-arm64`. `linux-arm64` is cross-compiled on a Linux x64 host:
`build.sh` installs Chromium's arm64 sysroot itself, and `bundle.py` needs the
aarch64 cross binutils (`binutils-aarch64-linux-gnu` on Debian/Ubuntu). `build.sh` selects
`/Applications/Xcode.app` through `DEVELOPER_DIR` for the build only. The checkout and build
need about 20 GB in `$OXGL_ANGLE_WORK` (default `~/.cache/oxgl/angle-build`).

```sh
angle/build.sh all macos-arm64          # or linux-x64, linux-arm64; Windows: pwsh angle/build.ps1 all [windows-x64|windows-arm64]
cc -I ~/.cache/oxgl/angle-build/dist/angle-macos-arm64/include angle/smoke/smoke.c -o smoke
./smoke ~/.cache/oxgl/angle-build/dist/angle-macos-arm64/lib
```

To try a local build in oxgl, point its build at the extracted bundle:
`OXGL_ANGLE_DIR=~/.cache/oxgl/angle-build/dist/angle-macos-arm64 npm run build`
in an oxgl checkout.

## Changing ANGLE

The recipe is every file that builds or tests a bundle: `pin.toml`, `args/`,
`build.sh`, `build.ps1`, `scripts/bundle.py`, `scripts/pin.sh`, `smoke/`,
`licenses.toml` and `license-texts/`. Any recipe change (a new ANGLE commit,
GN args, targets, scripts, license data) gets a new `bundle_version`:
published bundles are never rebuilt or replaced, because rebuilds are not
bit-identical and older oxgl commits pin the old digests.

The `angle-build` workflow runs on every pull request and reports one
`angle-build` check, which branch protection requires. It builds and
smoke-tests all five platforms when the recipe or the workflow itself changed,
and skips the builds otherwise. A change to the workflow alone (such as a
Dependabot action bump) builds and smoke-tests but needs no new
`bundle_version`, since nothing is released from a pull request.

1. Optionally iterate locally first: change the recipe, run
   `angle/build.sh all <platform>` (later runs recompile only what changed) and
   point oxgl at the result with `OXGL_ANGLE_DIR`.
2. Open a PR with the recipe change and a bumped `bundle_version` in
   `pin.toml` (`angle-NNNN.<n+1>`; for a new ANGLE version, pick the commit
   Chrome stable ships, listed on chromiumdash.appspot.com, and set
   `angle_commit`, `chromium_branch` and `angle-<branch>.1`). `angle-build`
   fails within seconds if the version is already released, within minutes if
   a GN arg or license check fails (`bundle.py --preflight`), and otherwise
   builds, checks and smoke-tests all five platforms.
3. After it merges, run `angle-build` by hand from `main` (Actions →
   angle-build → Run workflow). That run creates a draft release named after
   `bundle_version`, with the digests in its summary.
4. In oxgl, copy each platform's URL and sha256, and the `bundle_version`,
   into `angle/bundles.toml`, run `python3 angle/scripts/check_pin.py`, and open
   a PR. oxgl's CI builds and tests against the new bundles; after an ANGLE
   update, also recheck oxgl's "Known upstream issues" (its `angle/README.md`).
5. When that PR merges, publish the release:
   `gh release edit <bundle_version> --draft=false`.

A deleted or broken release asset is replaced the same way, under a new
`bundle_version`.
