# oxgl-angle

The build recipe for the [ANGLE](https://chromium.googlesource.com/angle/angle)
bundles that [oxgl](https://github.com/jerryryle/oxgl) renders with. It builds
ANGLE (with SwiftShader as the software fallback) from a pinned revision for
five platforms and publishes the bundles as releases of this repository. oxgl
pins a release's URLs and digests in its own `angle/bundles.toml`.

See [angle/README.md](angle/README.md) for the recipe, building locally and
releasing a new bundle version. BSD-3-Clause; each bundle carries the license
texts of everything it contains in `licenses/`.

