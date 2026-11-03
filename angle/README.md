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
| `scripts/skip_deps.py` | Makes `gclient sync` skip DEPS entries no bundle target uses, such as `third_party/clang-format/script`, whose pinned commit the mirror no longer serves |
| `scripts/check_pin.py` | Validates `pin.toml` |
| `scripts/bump.py` | Pins `pin.toml` to the ANGLE commit Chrome stable ships (run daily by `angle-bump`) |
| `scripts/pin_only.sh` | Whether an `angle-bump` branch changes only `pin.toml` (no fix pushed on top) |
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

The Linux bundles also enable ANGLE's OpenGL ES backend, which oxgl uses on
GPUs whose Vulkan driver ANGLE caps at OpenGL ES 2.0 (such as the Raspberry
Pi 5's V3D). It reaches the system's EGL through Mesa's surfaceless platform
and opens `libEGL.so.1` with `dlopen` only when that display is initialized,
so the libraries link no EGL, GL, GBM or libdrm library and load on machines
without Mesa. ANGLE's own libdrm copy (`third_party/libdrm`) is linked
statically and must stay unexported.

`bundle.py` fails the build if a required library or the ICD manifest is
missing, a required backend is not enabled, a linked component's license is
missing or not on the allowlist in `deny.toml`, or (Linux) a library links
X11/xcb/Wayland or the system EGL/GL/GBM/libdrm libraries, exports `drm*`
symbols, or needs glibc newer than 2.31. On Linux arm64 it also fails
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
| `angle-gles-rgb8-implementation-read-format.patch` | Makes ANGLE's OpenGL backend advertise `RGBA`/`UNSIGNED_BYTE` as the implementation read format of an `RGB8` color buffer when the native driver is OpenGL ES (`FramebufferGL::getImplementationColorReadFormat`, `src/libANGLE/renderer/gl/FramebufferGL.cpp`). ANGLE advertised `RGB`, the attachment's own format, and passed an `RGB` read to the driver unchanged. An OpenGL ES driver accepts only `RGBA`/`UNSIGNED_BYTE` and its own chosen pair (ES 3.0.6 §4.3.2), and Mesa stores `RGB8` padded and chooses `RGBA`, so the driver rejected the read. In a WebGL context ANGLE turns that backend error into a context loss (`loseHardenedContextOnBackendError`), so on Mesa (V3D, llvmpipe) any WebGL page reading an `alpha: false` canvas or an `RGB` render target in the advertised format lost its context. With the patch the advertised pair is one every driver accepts, and an `RGB` read is refused by ANGLE's validation with `INVALID_OPERATION`, before the driver sees it. The patch adds `ReadPixelsTest.RGBImplementationColorReadFormat`, which reads an `RGB` texture attachment in its advertised format and type. It fails without the fix on the OpenGL backend over a driver that chooses `RGBA` for `RGB8`, such as Mesa. The bundle builds don't build ANGLE's tests, so the test was run only on macOS (Metal and SwiftShader, which pass with or without the fix); the OpenGL ES path was checked on the Linux bundles with a C probe and oxgl's tests on Mesa's V3D and llvmpipe. |
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
`patches/`, `build.sh`, `build.ps1`, `scripts/bundle.py`, `scripts/pin.sh`, `scripts/skip_deps.py`, `smoke/`,
`licenses.toml` and `license-texts/`. Any recipe change (a new ANGLE commit,
GN args, targets, source patches, scripts, license data) gets a new
`bundle_version`:
published bundles are never rebuilt or replaced, because rebuilds are not
bit-identical and older oxgl commits pin the old digests.

The `angle-build` workflow reports one `angle-build` check, which branch
protection and the merge queue require. Changes reach `main` through the merge
queue. A pull request runs workflow lint and the `bundle_version` guard; with the
`full-ci` label, its runs from its next push on also build and smoke-test it,
and a manual run of `angle-build` on its branch does so at once. The queue builds and
smoke-tests all five platforms when the recipe or the workflow itself changed,
and skips the builds otherwise. A change to the workflow alone (such as a
Dependabot action bump) builds and smoke-tests but needs no new
`bundle_version`, since only a recipe change releases. When a recipe change
lands, the `angle-build` run on `main` builds nothing: it publishes the bundles
the queue run built and smoke-tested, as the release named after
`bundle_version`, with the digests in its summary, and then starts oxgl's
`angle-bump` workflow, which proposes the release. If that run fails, rerun it.
A recipe change merged past the queue has no queue run to release from: run
`angle-build` by hand from `main` (Actions → angle-build → Run workflow), which
builds, smoke-tests and releases it.

The guard fails a recipe change whose `bundle_version` is already released, or
isn't greater than the one at the commit it's built on (a pull request's base,
or the entry queued ahead of it), so two recipe changes queued back to back
can't share a version.

### New Chrome stable releases

The `angle-bump` workflow checks daily for a new Chrome stable release whose
Chromium DEPS pins a newer ANGLE commit (`scripts/bump.py`; it never follows
stable back to an older branch or an older commit on the pinned one). It sets
`angle_commit`, `chromium_branch` and `bundle_version` (`angle-<branch>.1` on
a new branch, `.<n+1>` on the pinned one), opens a pull request from the
`angle-bump` branch and turns on auto-merge, so it lands through the merge
queue once its checks pass, and the push to `main` releases it.

A bump that fails in the queue (say, a patch no longer applies) leaves the
queue and stays open: push the fix to `angle-bump`, and it lands through the
queue once its checks pass. The daily run leaves a branch carrying such a fix
alone. Otherwise it rebuilds an open bump only when the pin it would make
changed (Chrome stable moved, or `main`'s `pin.toml` did), so a bump building
in the queue isn't pulled out, and closes one `main` no longer needs. To skip
an ANGLE commit, add the `skip-bump` label to its pull request and close it;
remove the label to retry.

The bump opens its pull request as the `oxgl-js` GitHub App (secrets
`OXGL_BOT_CLIENT_ID` and `OXGL_BOT_PRIVATE_KEY`), because pull requests made
with the default `GITHUB_TOKEN` start no CI and couldn't enter the queue. The
release itself uses the default token, so oxgl's bump sees
`github-actions[bot]` as its author and uploader. No review is required: anyone
with write access can land a change, and a passing Chrome-stable bump lands,
releases and reaches oxgl's bump without a person. This repository accepts
that because it has a single maintainer. With more maintainers, require a
review and list the App as a ruleset bypass actor.

### By hand

1. Optionally iterate locally first: change the recipe, run
   `angle/build.sh all <platform>` (later runs recompile only what changed) and
   point oxgl at the result with `OXGL_ANGLE_DIR`.
2. Open a PR with the recipe change and a bumped `bundle_version` in
   `pin.toml` (`angle-NNNN.<n+1>`, greater than `main`'s; for a new ANGLE version, pick the commit
   Chrome stable ships, listed on chromiumdash.appspot.com, and set
   `angle_commit`, `chromium_branch` and `angle-<branch>.1`). `angle-build`
   fails within seconds if the version is already released or not greater than
   the base's. To build, check and smoke-test all five platforms before queueing it,
   run `angle-build` by hand on its branch, or label it `full-ci` and push; the queue does that in any case, failing
   within minutes if a GN arg or license check fails (`bundle.py --preflight`).
3. Queue it (Merge when ready). After it lands, the `angle-build` run on
   `main` publishes the release and starts oxgl's bump.
4. oxgl's bump opens a pull request pinning the release and lands it through
   oxgl's queue, which runs the full suite against the new bundles. If it fails
   there, fix it on oxgl's `angle-bump` branch. After an ANGLE update, also
   recheck oxgl's "Known upstream issues" (its `angle/README.md`). This applies
   to an automatic bump too.

A deleted or broken release asset is replaced the same way, under a new
`bundle_version`.
