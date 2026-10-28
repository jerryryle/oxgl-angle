#!/usr/bin/env python3
"""Assembles, checks and archives an oxgl ANGLE bundle from a finished build.

    bundle.py <platform> <out-dir> <angle-src> <dist-dir> <bundle-version> <angle-commit>
    bundle.py --preflight <platform> <out-dir> <angle-src>

--preflight runs only the checks that need no compiled output (required GN
args, component licenses), right after `gn gen`, so they fail before the
long compile instead of after it.

Produces <dist-dir>/angle-<platform>.tar.xz (stripped libraries, headers,
licenses, BUILD_INFO.json) and angle-<platform>-symbols.tar.xz (unstripped
libraries), and prints the bundle's sha256. Fails if any outcome check fails:
missing files, a component license that is not on the allowlist in deny.toml,
display-server linkage or a too-new glibc on Linux, a load segment aligned below
64 KiB on Linux arm64, or a required backend that is not enabled.
"""

import hashlib
import json
import platform as host
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# linux-arm64 is cross-compiled on an x64 host, whose binutils only understand
# x86 ELF; use the aarch64 cross binutils there (binutils-aarch64-linux-gnu).
CROSS_BINUTILS = {"linux-arm64": "aarch64-linux-gnu-"}
GLIBC_MAX = (2, 31)
# Linux arm64 kernels use 4, 16 or 64 KiB pages; a library loads under all of
# them only if every LOAD segment is aligned to the largest.
ARM64_MIN_ALIGN = 0x10000
FORBIDDEN_NEEDED = ("libX11", "libxcb", "libwayland-client")
REQUIRED_ARGS = {
    "common": {"angle_enable_vulkan": "true", "angle_enable_swiftshader": "true", "angle_enable_wgpu": "false"},
    "macos-arm64": {"angle_enable_metal": "true"},
    "linux-x64": {"angle_use_x11": "false", "angle_use_wayland": "false"},
    "linux-arm64": {"angle_use_x11": "false", "angle_use_wayland": "false"},
    "windows-x64": {"angle_enable_d3d11": "true"},
    "windows-arm64": {"angle_enable_d3d11": "true"},
}
LIB_PATTERNS = {
    "macos-arm64": ("libEGL.dylib", "libGLESv2.dylib", "libvk_swiftshader.dylib", "libvulkan*.dylib"),
    "linux-x64": ("libEGL.so", "libGLESv2.so", "libvk_swiftshader.so", "libvulkan.so*"),
    "linux-arm64": ("libEGL.so", "libGLESv2.so", "libvk_swiftshader.so", "libvulkan.so*"),
    "windows-x64": ("libEGL.dll", "libGLESv2.dll", "vk_swiftshader.dll", "vulkan-1.dll"),
    "windows-arm64": ("libEGL.dll", "libGLESv2.dll", "vk_swiftshader.dll", "vulkan-1.dll"),
}
REQUIRED_LIBS = dict.fromkeys(LIB_PATTERNS, 3)  # EGL, GLESv2, SwiftShader
HEADER_DIRS = ("EGL", "GLES2", "GLES3", "KHR")
LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.TXT", "LICENSE.md", "COPYING", "NOTICE", "NOTICE.txt")


def fail(message: str) -> None:
    sys.exit(f"bundle: {message}")


def run(program: str, *args: str, cwd: Path | None = None) -> str:
    # shutil.which honours PATHEXT, so depot_tools' gn.bat is found on Windows,
    # where subprocess alone only resolves .exe files.
    executable = shutil.which(program) or program
    return subprocess.run([executable, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def allowlist() -> set[str]:
    with open(REPO / "deny.toml", "rb") as f:
        allow = tomllib.load(f).get("licenses", {}).get("allow")
    if not isinstance(allow, list):
        fail("cannot find [licenses] allow in deny.toml")
    return set(allow)


def license_parts(spdx: str) -> list[str]:
    """The allowlist entries an SPDX expression from README.chromium needs."""
    return [p.strip() for p in re.split(r"\s+AND\s+|,", spdx) if p.strip()]


def overrides() -> dict[str, dict]:
    """License metadata for third_party directories README.chromium doesn't cover."""
    with open(REPO / "angle" / "licenses.toml", "rb") as f:
        return tomllib.load(f).get("components", {})


def effective_args(src: Path, out: Path, platform: str) -> dict[str, str]:
    names = {**REQUIRED_ARGS["common"], **REQUIRED_ARGS[platform]}
    values = {}
    for name in names:
        text = run("gn", "args", str(out), f"--list={name}", "--short", cwd=src)
        match = re.search(rf"^{name}\s*=\s*(\S+)", text, re.M)
        if not match:
            fail(f"GN arg {name} does not exist at this ANGLE revision")
        values[name] = match.group(1)
        if values[name] != names[name]:
            fail(f"GN arg {name} is {values[name]}, required {names[name]}")
    return values


def component_dirs(src: Path, out: Path) -> list[str]:
    """third_party directories that contribute code to the shipped targets."""
    targets = (REPO / "angle" / "args" / "targets.txt").read_text().split()
    dirs = set()
    for target in targets:
        label = f"//{target}" if ":" in target else f"//:{target}"
        deps = run("gn", "desc", str(out), label, "deps", "--all", cwd=src)
        for label in deps.split():
            match = re.match(r"//((?:third_party/[^/:]+/)*third_party/[^/:]+)", label)
            if match:
                dirs.add(match.group(1))
    return sorted(dirs)


def readme_license(directory: Path) -> tuple[str | None, list[Path]]:
    """SPDX license and license files from the nearest README.chromium."""
    for candidate in [directory, *directory.parents]:
        readme = candidate / "README.chromium"
        if readme.exists():
            text = readme.read_text(errors="replace")
            license_match = re.search(r"^License:\s*(.+)$", text, re.M)
            files_match = re.search(r"^License File:\s*(.+)$", text, re.M)
            files = [candidate / f.strip() for f in files_match.group(1).split(",")] if files_match else []
            return (license_match.group(1).strip() if license_match else None), files
        if candidate.name == "third_party":
            break
    return None, []


def collect_licenses(src: Path, out: Path, stage: Path) -> list[dict[str, str]]:
    allowed = allowlist()
    known = overrides()
    licenses_dir = stage / "licenses"
    licenses_dir.mkdir()
    components = [{"name": "angle", "path": ".", "license": "BSD-3-Clause"}]
    shutil.copy(src / "LICENSE", licenses_dir / "angle.LICENSE")
    problems = []
    for rel in component_dirs(src, out):
        directory = src / rel
        if rel in known:
            spdx = known[rel]["license"]
            texts = [REPO / f[5:] if f.startswith("repo:") else src / f for f in known[rel]["files"]]
        else:
            spdx, texts = readme_license(directory)
            texts = texts or [p for n in LICENSE_NAMES if (p := directory / n).exists()]
        name = rel.replace("third_party/", "").replace("/", "-")
        if not spdx:
            problems.append(f"{rel}: no license metadata (add it to angle/licenses.toml)")
            continue
        disallowed = [p for p in license_parts(spdx) if p not in allowed]
        if disallowed:
            problems.append(f"{rel}: license {spdx} not on the allowlist")
        missing = [str(t) for t in texts if not t.is_file()]
        if not texts or missing:
            problems.append(f"{rel}: license text not found {missing}")
            continue
        for text in texts:
            # Named by relative path: a component may list several files with the
            # same basename (src/LICENSE, src/third_party/x/LICENSE).
            base = REPO if text.is_relative_to(REPO) else src
            flat = text.relative_to(base).as_posix().replace("/", "__")
            target = licenses_dir / f"{name}.{flat}"
            if target.exists():
                fail(f"license file name collision: {target.name}")
            shutil.copy(text, target)
        components.append({"name": name, "path": rel, "license": spdx})
    if problems:
        fail("license check failed:\n  " + "\n  ".join(problems))
    return components


def binutil(platform: str, tool: str) -> str:
    prefix = CROSS_BINUTILS.get(platform, "")
    return f"{prefix}{tool}" if prefix and host.machine() not in ("aarch64", "arm64") else tool


def linux_checks(libs: list[Path], platform: str) -> str:
    newest = (0, 0)
    for lib in libs:
        needed = run("readelf", "-d", str(lib))
        for bad in FORBIDDEN_NEEDED:
            if bad in needed:
                fail(f"{lib.name} links {bad}")
        for major, minor in re.findall(r"GLIBC_(\d+)\.(\d+)", run(binutil(platform, "objdump"), "-T", str(lib))):
            newest = max(newest, (int(major), int(minor)))
    if newest > GLIBC_MAX:
        fail(f"bundle needs glibc {newest[0]}.{newest[1]}, above the {GLIBC_MAX[0]}.{GLIBC_MAX[1]} baseline")
    return f"{newest[0]}.{newest[1]}"


def min_load_align(lib: Path) -> int:
    """The smallest LOAD segment alignment in an ELF library's program headers."""
    aligns = [int(line.split()[-1], 16) for line in run("readelf", "-lW", str(lib)).splitlines()
              if line.split()[:1] == ["LOAD"]]
    if not aligns:
        fail(f"{lib.name} has no LOAD segments")
    return min(aligns)


def arm64_alignment_check(libs: list[Path]) -> str:
    smallest = None
    for lib in libs:
        align = min_load_align(lib)
        if align < ARM64_MIN_ALIGN:
            fail(f"{lib.name} has a LOAD segment aligned to {align:#x}, below the {ARM64_MIN_ALIGN:#x} "
                 "needed to load on every arm64 page size")
        smallest = align if smallest is None else min(smallest, align)
    return f"{smallest:#x}"


def strip(lib: Path, platform: str) -> None:
    if platform == "macos-arm64":
        run("strip", "-x", str(lib))
    elif platform.startswith("linux-"):
        run(binutil(platform, "strip"), "--strip-unneeded", str(lib))
    # Windows symbols already live in separate .pdb files.


def archive(directory: Path, target: Path) -> None:
    with tarfile.open(target, "w:xz") as tar:
        for path in sorted(directory.rglob("*")):
            tar.add(path, arcname=path.relative_to(directory), recursive=False)


def preflight(platform: str, out: Path, src: Path) -> None:
    effective_args(src, out, platform)
    with tempfile.TemporaryDirectory() as scratch:
        collect_licenses(src, out, Path(scratch))
    print(f"preflight passed for {platform}")


def main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "--preflight":
        platform, out, src = sys.argv[2:]
        if platform not in LIB_PATTERNS:
            fail(f"unknown platform {platform}")
        preflight(platform, Path(out), Path(src))
        return
    if len(sys.argv) != 7:
        fail("usage:\n" + "\n".join(__doc__.strip().splitlines()[2:4]))
    platform, out, src, dist, version, commit = sys.argv[1:]
    out, src, dist = Path(out), Path(src), Path(dist)
    if platform not in LIB_PATTERNS:
        fail(f"unknown platform {platform}")

    stage = dist / f"angle-{platform}"
    symbols = dist / f"angle-{platform}-symbols"
    for d in (stage, symbols):
        shutil.rmtree(d, ignore_errors=True)
    (stage / "lib").mkdir(parents=True)
    symbols.mkdir(parents=True)

    libs = []
    for pattern in LIB_PATTERNS[platform]:
        for path in sorted(out.glob(pattern)):
            if path.suffix == ".TOC" or path.is_symlink():
                continue
            shutil.copy(path, symbols / path.name)
            pdb = path.with_name(f"{path.name}.pdb")  # Windows debug symbols, e.g. libGLESv2.dll.pdb
            if pdb.exists():
                shutil.copy(pdb, symbols / pdb.name)
            shutil.copy(path, stage / "lib" / path.name)
            strip(stage / "lib" / path.name, platform)
            libs.append(stage / "lib" / path.name)
    if len(libs) < REQUIRED_LIBS[platform]:
        fail(f"expected EGL, GLESv2 and SwiftShader libraries in {out}, found {[p.name for p in libs]}")
    icd = out / "vk_swiftshader_icd.json"
    if not icd.exists():
        fail(f"missing {icd.name}")
    shutil.copy(icd, stage / "lib" / icd.name)

    for header_dir in HEADER_DIRS:
        shutil.copytree(src / "include" / header_dir, stage / "include" / header_dir)

    args = effective_args(src, out, platform)
    components = collect_licenses(src, out, stage)
    glibc = linux_checks(libs, platform) if platform.startswith("linux-") else None
    load_align = arm64_alignment_check(libs) if platform == "linux-arm64" else None

    clang_rev = src / "third_party" / "llvm-build" / "Release+Asserts" / "cr_build_revision"
    info = {
        "bundle_version": version,
        "platform": platform,
        "angle_commit": commit,
        "built_on": f"{host.system()} {host.release()}",
        "clang_revision": clang_rev.read_text().strip() if clang_rev.exists() else None,
        "macos_sdk": run("xcrun", "--show-sdk-version").strip() if platform == "macos-arm64" else None,
        "glibc_max": glibc,
        "min_load_align": load_align,
        "gn_args": args,
        "gn_args_file": (out / "args.gn").read_text(),
        "components": components,
        "files": {str(p.relative_to(stage)): sha256(p) for p in sorted(stage.rglob("*")) if p.is_file()},
    }
    (stage / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n")

    bundle = dist / f"angle-{platform}.tar.xz"
    archive(stage, bundle)
    archive(symbols, dist / f"angle-{platform}-symbols.tar.xz")
    print(f"{bundle.name} sha256={sha256(bundle)}")


if __name__ == "__main__":
    main()
