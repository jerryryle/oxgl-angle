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
| `scripts/skip_deps.py` | Makes `gclient sync` skip DEPS entries no bundle target uses: `third_party/clang-format/script`, whose pinned commit the mirror no longer serves, and on Linux the Android SDK, NDK and JDK, which ANGLE's `bootstrap.py` requests and which filled CI runners' disks |
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
| `angle-gl-copyteximage-float-framebuffer.patch` | Backports the part of upstream ANGLE commit 6cb4025008 ("GL: work around glCopyTexImage / glCopyTexSubImage bugs", after the pinned branch) that makes ANGLE's OpenGL backend keep a float source's component type in `copyTexImage2D` (`TextureGL::copyImage`, `nativegl::GetCopyTexImageInternalFormatInfo` in `formatutilsgl.cpp`, the LUMA workaround in `BlitGL.cpp`, and `TextureImpl::getCopyImageInternalFormat`, which `Texture::copyImage` now asks for the format it records). The pinned code resolved an unsized destination format (`RGBA`, `RGB`, `LUMINANCE`, ...) with `UNSIGNED_BYTE`, so WebGL 1's `copyTexImage2D` from a half-float framebuffer (`EXT_color_buffer_half_float`) asked the driver for a float-to-fixed-point copy, which ES 3.0 §3.8.5 forbids. Mesa refused it with `INVALID_OPERATION`, and in a WebGL context ANGLE turns that backend error into a context loss (`loseHardenedContextOnBackendError`), failing Khronos `conformance/extensions/ext-color-buffer-half-float.html` on Mesa (V3D, llvmpipe). With the patch the destination gets the source's half-float (or float) format, as WebGL 1 allows. For `LUMINANCE`, `ALPHA` and `LUMINANCE_ALPHA` destinations that alone is not enough, and upstream `main` still fails on Mesa: ES 3.0 has no sized float luminance or alpha formats, and Mesa refuses a float copy into the unsized ones. Going beyond upstream, the patch backs every float luminance/alpha texture with `R16F`/`RG16F` (or `R32F`/`RG32F`) on ES 3 drivers (`GetNativeInternalFormat`, `GetNativeFormat`, `GetNativeType`), as ANGLE already did for drivers without `OES_texture_half_float` or `OES_texture_float`. ANGLE's existing LUMA emulation then copies into them through a float scratch texture, whether the texture came from `copyTexImage2D` or `texImage2D`. It also makes that emulation pass the ES 3 `HALF_FLOAT` type instead of `HALF_FLOAT_OES` for the scratch and destination textures (`BlitGL.cpp`). A copy of a texture level into itself now records the level's LUMA emulation, as upstream does, and copies through the same swizzle (`handleCopyImageSelfCopyRedefine`); before, a self-copy into an emulated `ALPHA` took the red channel. Upstream's PowerVR scratch-texture workaround and its virtualized-mipchain changes are left out: the pin has neither. The patch carries upstream's `WebGLCompatibilityTest.CopyTexImageFromFloatFramebufferPreservesType` and adds `CopyTexImageTest.HalfFloatToSameTextureLUMA`, which self-copies into luminance/alpha formats in an ES 2 context (WebGL refuses self-copies as feedback loops). It fails without the fix on the OpenGL backend over an OpenGL ES driver that enforces §3.8.5, such as Mesa. The bundle builds don't build ANGLE's tests, and macOS offers no OpenGL test configuration, so the tests were run only on macOS with Metal and SwiftShader, which pass with or without the fix, alongside the existing `ReadPixels*`, `WebGL*CompatibilityTest`, `*CopyTex*` and `Texture*` tests (3,871 in all, all passing). The OpenGL ES path was checked on the CI-built `linux-arm64` bundle with a C probe that uses a fresh WebGL 1 context per case. It copies an `RGBA`/`HALF_FLOAT_OES` framebuffer into `RGBA`, `RGB`, `LUMINANCE`, `ALPHA` and `LUMINANCE_ALPHA`, in bounds and partly outside, then `copyTexSubImage2D`s into each copy and samples it. Before the patch every copy failed with `INVALID_OPERATION` and lost the context, on both Mesa's V3D (Raspberry Pi 5) and llvmpipe. With the patch, all copies succeeded and sampled the source colour on llvmpipe before the `texImage2D` and self-copy changes were added; on V3D only the `RGBA` and `RGB` copies have been checked. The current patch has not been probed on Mesa yet. |
| `angle-gles-implementation-read-format.patch` | Makes ANGLE's OpenGL backend advertise, when the native driver is OpenGL ES, an implementation read format and type that ES 3.0.6 §4.3.2 requires every driver to accept (`FramebufferGL::getImplementationColorReadFormat`, `src/libANGLE/renderer/gl/FramebufferGL.cpp`): `RGBA`/`UNSIGNED_BYTE` for an `RGB8` color buffer, and `RGBA_INTEGER`/`UNSIGNED_INT` for a 16-bit unsigned integer one (`RGBA16UI`, `RG16UI`, `R16UI`). Other integer formats keep their own pair, which Mesa accepts. ANGLE advertised the attachment's own format and type and passed such a read to the driver unchanged, but a driver accepts only the required pair and its own chosen one. Mesa stores `RGB8` padded and chooses `RGBA`, and refuses `UNSIGNED_SHORT` for 16-bit unsigned integer buffers (`RGBA16UI`, `R16UI`), so the driver rejected those reads. In a WebGL context ANGLE turns that backend error into a context loss (`loseHardenedContextOnBackendError`), so on Mesa (V3D, llvmpipe) a WebGL page reading an `alpha: false` canvas, an `RGB` render target or a 16-bit unsigned integer one in the advertised format lost its context (Khronos `conformance2/reading/read-pixels-from-fbo-test.html`). With the patch the advertised pair is one every driver accepts, and a read in the attachment's own pair, where it differs, is refused by ANGLE's validation with `INVALID_OPERATION` before the driver sees it. The patch adds `ReadPixelsTest.RGBImplementationColorReadFormat` and `ReadPixelsTest.IntegerImplementationColorReadFormat`, which read an `RGB` texture and integer renderbuffers in their advertised format and type. They fail without the fix on the OpenGL backend over a driver that chooses differently, such as Mesa. The bundle builds don't build ANGLE's tests, and macOS offers no OpenGL test configuration, so the tests were run only on macOS with Metal and SwiftShader, which pass with or without the fix, alongside the existing `ReadPixels*`, `WebGL*CompatibilityTest`, `*CopyTex*` and `Texture*` tests (3,871 in all, all passing). The OpenGL ES path was checked on the CI-built `linux-arm64` bundle with a C probe that reads `RGBA16UI`, `RGBA8UI`, `R16UI`, `RGB10_A2UI`, `RGBA32UI`, `RGBA16I` and `R8I` renderbuffers in their advertised format in a WebGL 2 context. Before the patch, the `RGBA16UI` and `R16UI` reads failed with `INVALID_OPERATION` and lost the context, on both Mesa's V3D (Raspberry Pi 5) and llvmpipe. With the patch, every read succeeded with the cleared value on both, then with every integer format advertising `RGBA_INTEGER`/`UNSIGNED_INT` or `INT`. Narrowing that to the 16-bit unsigned formats came later and has not been probed on Mesa yet. |
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
