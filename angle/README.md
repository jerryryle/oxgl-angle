# ANGLE bundles

oxgl renders through [ANGLE](https://chromium.googlesource.com/angle/angle),
with SwiftShader as the software fallback. Google publishes no ANGLE binaries,
so oxgl builds its own from a pinned revision and publishes them as GitHub
release assets. Everything else (developers, CI, npm builds) downloads those
bundles and verifies them against digests committed here, so ANGLE is built
only when its recipe changes.

Bundles are built for five platforms: `linux-x64`, `linux-arm64`,
`macos-arm64`, `windows-x64` and `windows-arm64`. oxgl itself currently
supports only Linux arm64 (see the top-level README); the other bundles keep
the recipe working for when those platforms return. The arm64 Linux and
Windows bundles are cross-compiled on x64 hosts, as Chromium does, and
smoke-tested on arm64 runners.

## Files

| File | Purpose |
|---|---|
| `pin.toml` | Recipe inputs: ANGLE commit, depot_tools commit, `bundle_version` (release tag) |
| `bundles.toml` | Build outputs: per-platform bundle URL + sha256 that oxgl-sys downloads, and optionally a symbols archive (`symbols_url`, `symbols_sha256`) that it uses instead of the stripped libraries when `OXGL_ANGLE_SYMBOLS` is set |
| `args/*.gn` | GN build arguments: `common.gn` plus one file per platform |
| `args/targets.txt` | Ninja targets to build |
| `build.sh`, `build.ps1` | Build recipe (`fetch`, `build`, `bundle`, `all`) for macOS/Linux and Windows (x64 and arm64) |
| `scripts/bundle.py` | Assembles the bundle and enforces the outcome checks |
| `scripts/check_pin.py` | Validates `pin.toml` and `bundles.toml` |
| `licenses.toml` | SPDX licenses for third_party directories lacking `README.chromium` metadata |
| `smoke/smoke.c` | Loads a bundle, renders one frame with SwiftShader, reads a pixel back |

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

## How oxgl-sys finds a bundle

`crates/oxgl-sys/build.rs` uses, in order:

1. `OXGL_ANGLE_DIR`: an extracted bundle directory (offline builds, or testing a
   local ANGLE build). The build prints a warning while this is set.
2. The cache: `$OXGL_ANGLE_CACHE`, default `~/.cargo/oxgl-angle/<sha256>/`.
3. A download of the URL in `bundles.toml` with `curl`, verified against its
   sha256 before anything is extracted. A mismatch fails the build.

When `pin.toml` names a newer `bundle_version` than `bundles.toml` (a recipe
change has merged but its bundles are not pinned yet), the build uses the older
bundles and prints a warning.

`npm run build` then copies the bundle's `lib/` to `dist/angle/` next to the
addon and writes `dist/THIRD_PARTY_NOTICES` with the ANGLE license texts.

`build.rs` also re-checks the bundle's component licenses (from
`BUILD_INFO.json`) against today's `deny.toml` allowlist and fails if one is no
longer allowed: narrowing the allowlist needs a bundle built under it (see
Changing ANGLE), or the change reverted.

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
OXGL_ANGLE_DIR=~/.cache/oxgl/angle-build/dist/angle-macos-arm64 npm run build
```

## Changing ANGLE

The recipe is every file that builds or tests a bundle: `pin.toml`, `args/`, `build.sh`, `build.ps1`, `scripts/bundle.py`, `scripts/pin.sh`, `smoke/`, `licenses.toml`, `license-texts/`, and
`.github/workflows/angle-build.yml`. `angle-build` runs only for those. Any recipe change (a new ANGLE commit, GN args, targets, scripts,
license data) gets a new `bundle_version`: published bundles are never rebuilt
or replaced, because rebuilds are not bit-identical and older commits pin the
old digests.

1. Optionally iterate locally first: change the recipe, run
   `angle/build.sh all <platform>` (later runs recompile only what changed) and
   point oxgl at the result with `OXGL_ANGLE_DIR`.
2. Open a PR with the recipe change and a bumped `bundle_version` in
   `pin.toml` (`angle-NNNN.<n+1>`; for a new ANGLE version, pick the commit
   Chrome stable ships, listed on chromiumdash.appspot.com, and set
   `angle_commit`, `chromium_branch` and `angle-<branch>.1`). `angle-build`
   runs: it fails within seconds if the version is already released, within
   minutes if a GN arg or license check fails (`bundle.py --preflight`), and
   otherwise builds, checks and smoke-tests all five platforms.
3. After it merges, run `angle-build` by hand from `main` (Actions →
   angle-build → Run workflow). That run creates a draft release named after
   `bundle_version`, with the digests in its summary.
4. Copy each platform's URL and sha256, and the `bundle_version`, into
   `bundles.toml`, run `python3 angle/scripts/check_pin.py`, and open a PR.
   This does not rebuild ANGLE; CI builds oxgl against the new bundles.
5. When that PR merges, publish the release without making it the
   repository's latest release (oxgl's own `v*` releases share the list):
   `gh release edit <bundle_version> --draft=false --latest=false`. If you
   publish from the Releases page instead, untick "Set as the latest release",
   which is ticked by default; the `--latest=false` set on the draft does not
   carry over.

A deleted or broken release asset is replaced the same way, under a new
`bundle_version`.

### Known upstream issues

ANGLE behavior oxgl does not work around, listed so that every ANGLE update
rechecks it.

#### Conformance failures

Khronos conformance pages that fail because of ANGLE, or of the SwiftShader it
bundles. Each is an expected failure in
`conformance/expectations.txt`, tagged `ANGLE:` or `SwiftShader:`. Last checked
against `angle_commit` `127e783de334` (`chromium/8078`).

| Page (suites) | Cause | Where |
| --- | --- | --- |
| `conformance/glsl/misc/shader-with-double-underscore.html` (webgl1, webgl2) | ANGLE rejects identifiers containing `__` in WebGL shaders; the test expects them to compile, as newer GLSL ES allows. Still so on ANGLE `main` (October 2026). | `TParseContext::checkIsNotReserved`, `src/compiler/translator/ParseContext.cpp` |
| `conformance2/textures/misc/immutable-tex-render-feedback.html` (webgl2) | A mutable texture's level is attached while its range is empty (`TEXTURE_BASE_LEVEL` 1, `TEXTURE_MAX_LEVEL` 0); ANGLE reports the framebuffer complete instead of `FRAMEBUFFER_INCOMPLETE_ATTACHMENT` (OpenGL ES 3.0 §4.4.4). Fails on Metal too. | ANGLE's framebuffer completeness checks |
| `conformance/uniforms/uniform-default-values.html` (webgl1, webgl2) | SwiftShader samples a white `UNORM8` texel as about 0.99994, not exactly 1.0. Passes on GPU backends. | SwiftShader's sampler |
| `deqp/functional/gles3/shaderoperator/unary_operator_00.html` (webgl2) | SwiftShader fails `shaderop.unary_operator.minus.lowp_uint_vertex`. Passes on GPU backends. | SwiftShader |

After changing `angle_commit`, run the full suite (`npm run conformance`) with
the new bundle. A page here that now passes is reported as `expected FAIL, got
PASS`, which fails the run: remove its expectation (`--update`) and its row,
and update the commit above. To check one page,
`npm run conformance -- --filter <page>`.

#### Runtime issues

ANGLE behavior that oxgl's README documents under "Known issues". Last checked
against `angle_commit` `127e783de334`; still present on `chromium/8127` and
`main` (October 2026).

| Issue | Cause | Where | When it is fixed |
| --- | --- | --- | --- |
| SwiftShader initialization briefly changes process-global state (`VK_ICD_FILENAMES`, and the working directory on Linux and Windows) | ANGLE points the Vulkan loader at SwiftShader's ICD through the environment and working directory | `angle::vk::ScopedVkLoaderEnvironment`, used in `src/libANGLE/renderer/vulkan/vk_renderer.cpp` | Remove the entry from oxgl's README "Known issues" |
| Each thread that uses EGL leaves 72 bytes behind | ANGLE allocates each thread's `egl::Thread` and Display TLS data on its first EGL call and never frees them ("Global thread intentionally leaked") | `src/libGLESv2/global_state.cpp`, `egl::GetCurrentThread` | Remove the README "Known issues" entry and the `leak:egl::GetCurrentThread` line in `.github/lsan-suppressions.txt` |

After changing `angle_commit`, check that the code above is still in the new
commit's sources. For the leak, also run the `asan` job without its
suppression: it reports the 72-byte allocations for as long as ANGLE makes them.
