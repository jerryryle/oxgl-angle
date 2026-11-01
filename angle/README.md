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
| `patches/*.patch` | Source patches applied to the ANGLE checkout before `gn gen`, for settings no GN arg reaches (see [Source patches](#source-patches)) |
| `build.sh`, `build.ps1` | Build recipe (`fetch`, `build`, `bundle`, `all`) for macOS/Linux and Windows (x64 and arm64) |
| `scripts/bundle.py` | Assembles the bundle and enforces the outcome checks |
| `scripts/check_pin.py` | Validates `pin.toml` |
| `scripts/bump.py` | Pins `pin.toml` to the ANGLE commit Chrome stable ships (run daily by `angle-bump`) |
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

## Source patches

`build.sh` and `build.ps1` apply each `patches/*.patch` to the ANGLE checkout
(paths relative to its root) before `gn gen`. A patch already applied by an
earlier build is skipped; one that no longer applies fails the build, so an
ANGLE update that moves the patched code has to update the patch.
`BUILD_INFO.json` does not list the patches: a released bundle was built with
the patches in the commit its tag points to.

| Patch | Why |
|---|---|
| `angle-incomplete-integer-texture-nearest-filter.patch` | Gives ANGLE's incomplete-texture stand-ins for integer samplers (`RGBA8UI` and `RGBA8I`, holding (0,0,0,max)) `NEAREST` min and mag filters in `IncompleteTextureSet::getIncompleteTexture` (`src/libANGLE/renderer/renderer_utils.cpp`). They kept the GL defaults (`LINEAR`, `NEAREST_MIPMAP_LINEAR`), so a filtered `texture()` call on an incomplete integer or stencil-mode texture made Vulkan linearly filter an integer format, which Vulkan leaves undefined (ANGLE suppresses the matching `VUID-vkCmdDraw-magFilter-04553`). SwiftShader filters integer texels as floats on their raw bits, so 255 becomes a denormal, and its worker threads flush denormals to zero wherever `CPUID::setFlushToZero` is implemented: x86 (MXCSR) and every MSVC build (`_controlfp`), but not Linux or macOS arm64. The stand-in therefore sampled as (0,0,0,0) on Linux x64, Windows x64 and Windows arm64, which failed "sampling stencil from incomplete texture" in Khronos `conformance2/extensions/webgl-stencil-texturing.html` (20 subtests). The patch adds `IncompleteTextureTestES3.IntegerTypeFilteredSample`, which samples incomplete `isampler2D` and `usampler2D` textures with `texture()`. The existing integer tests use `texelFetch`, which skips filtering. The test fails without the fix only where denormals are flushed, so on SwiftShader under x64 or Windows. It was checked on macOS arm64 with a local SwiftShader change, not part of this patch, that sets AArch64 `FPCR.FZ` on worker threads as Windows arm64 does: the test and the Khronos page fail without the fix and pass with it. Not covered: a sampler object bound to the unit still overrides the stand-in's filters, as it does for every backend. |
| `swiftshader-high-precision-filtering.patch` | Defines `SWIFTSHADER_HIGH_PRECISION_FILTERING` for SwiftShader's Vulkan driver. SwiftShader sets it only in Chromium builds (crbug.com/726075); without it, `LINEAR` filtering of 8-bit textures uses 16-bit fixed-point math and a white texel samples as about 0.99994, not 1.0, which fails Khronos `conformance/uniforms/uniform-default-values.html`. Chromium's `build/` has no GN arg for extra compiler flags outside its cros and unbundle toolchains, hence a patch. A local configuration change, not meant for upstream. |
| `swiftshader-jit-single-reservation.patch` | Makes SwiftShader's LLVM JIT map each routine's code, read-only data and read-write data in one block of pages, replacing `SectionMemoryManager` in `src/Reactor/LLVMJIT.cpp`. Mapped separately, the sections can land more than 4 GB apart, beyond the reach of AArch64's PC-relative `ADRP`, which the bundled LLVM 10 then patches without a range check, so the routine reads its constants from an address 8 GB off. On Windows arm64 that crashed the host process (access violation in a JIT routine) on about 13 of 3,836 Khronos conformance pages per run, whenever another allocation, such as a V8 WebAssembly memory, reserved address space between a routine's sections. The patch also makes LLVM 10 report an out-of-range `ADRP` relocation as a fatal error instead of wrapping (`RuntimeDyldCOFFAArch64.h`, `RuntimeDyldELF.cpp`). It adds `ReactorUnitTests.ConstantDataIsNearCode`, which checks that a routine's constant data lies within 1 MiB of its code and, on Windows, in the same allocation (same `VirtualQuery` `AllocationBase`). Only the Windows check fails without the fix, and it has not been run here: there is no Windows build of SwiftShader's tests. Elsewhere, separately mapped sections usually land next to each other, so the distance check passes with or without the fix (verified on macOS arm64 and Linux arm64); placing them far apart deterministically would need test-only allocation hooks. |

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
`patches/`, `build.sh`, `build.ps1`, `scripts/bundle.py`, `scripts/pin.sh`, `smoke/`,
`licenses.toml` and `license-texts/`. Any recipe change (a new ANGLE commit,
GN args, targets, source patches, scripts, license data) gets a new
`bundle_version`:
published bundles are never rebuilt or replaced, because rebuilds are not
bit-identical and older oxgl commits pin the old digests.

The `angle-build` workflow runs on every pull request and reports one
`angle-build` check, which branch protection requires. It builds and
smoke-tests all five platforms when the recipe or the workflow itself changed,
and skips the builds otherwise. A change to the workflow alone (such as a
Dependabot action bump) builds and smoke-tests but needs no new
`bundle_version`, since nothing is released from a pull request. When a recipe
change merges, `angle-build` builds and smoke-tests it again on `main` and
publishes the release named after `bundle_version`, with the digests in its
summary. If that run fails, rerun it, or run `angle-build` by hand from `main`
(Actions → angle-build → Run workflow).

### New Chrome stable releases

The `angle-bump` workflow checks daily for a new Chrome stable release whose
Chromium DEPS pins a different ANGLE commit (`scripts/bump.py`). It sets
`angle_commit`, `chromium_branch` and `bundle_version` (`angle-<branch>.1` on
a new branch, `.<n+1>` on the pinned one) and opens a pull request from the
`angle-bump` branch, then runs `angle-build` on that branch. When it passes,
the `merge-bump` job merges the pull request and runs `angle-build` on `main`,
which publishes the release. A bump that fails (say, a patch no longer
applies) stays open: push the fix to `angle-bump` and it merges once green. No
new bump opens while one is open.

Both workflows use only the default `GITHUB_TOKEN`. Its pushes, pull requests
and merges trigger no workflows, which is why they start `angle-build` with
`gh workflow run` instead. This relies on three repository settings: "Allow
GitHub Actions to create and approve pull requests" (Settings → Actions →
General), and, in the "Default (bypassable)" ruleset, no required approving
review and no extra approval for unattributed changes (both would hold a pull
request the workflow opened for a human review). The ruleset keeps the
required `angle-build` check.

### By hand

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
3. After it merges, the `angle-build` run on `main` publishes the release.
4. In oxgl, copy each platform's URL and sha256, and the `bundle_version`,
   into `angle/bundles.toml`, run `python3 angle/scripts/check_pin.py`, and open
   a PR. oxgl's CI builds and tests against the new bundles; after an ANGLE
   update, also recheck oxgl's "Known upstream issues" (its `angle/README.md`).
   Step 4 applies to an automatic bump too.

A deleted or broken release asset is replaced the same way, under a new
`bundle_version`.
