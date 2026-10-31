# oxgl-angle

The build recipe for the ANGLE bundles that oxgl renders with: ANGLE (with SwiftShader as the
software Vulkan backend) built from a pinned revision for Linux x64, Linux arm64, macOS arm64,
Windows x64 and Windows arm64, and published as releases of this repository. `angle/README.md`
describes the recipe, local builds and releasing.

## Recipe rules

- Any recipe change (`angle/pin.toml`, `args/`, `patches/`, `build.sh`, `build.ps1`, `scripts/`,
  `smoke/`, license data) gets a new `bundle_version`. Published bundles are never rebuilt or
  replaced: rebuilds are not bit-identical, and older oxgl commits pin the old digests.
- Keep `deny.toml` in step with oxgl's copy: oxgl re-checks every pinned bundle's licenses
  against its own.
- Every patch in `angle/patches/` has a row in `angle/README.md`'s "Source patches" table saying
  what it changes and why.

## Source patches are upstream-ready

Patches should be good enough to contribute to the project that owns the code, so each one is
written to that project's standards, not this repository's or oxgl's:

- Code in ANGLE itself follows the ANGLE coding standard,
  https://chromium.googlesource.com/angle/angle/+/HEAD/doc/CodingStandard.md (4-space indent, no
  tabs, lines under 100 columns, braces on their own line, `m` prefix for members,
  lowerCamelCase member functions, `k` prefix for constants), formatted as `git cl format` would.
- Code in a vendored project follows that project's own style: SwiftShader
  (`third_party/SwiftShader`) uses its `.clang-format` (Google-based, tab indentation, braces on
  their own line, no `m` prefix), and its bundled LLVM uses the LLVM coding standards
  (`clang-format --style=LLVM`). The ANGLE standard has no rule for `third_party/`, and Google's
  guide defers to the third-party project's own policies.
- Comments follow Google's comment guidance,
  https://google.github.io/styleguide/cppguide.html#comments: comment non-obvious classes and
  functions, start a function comment with a verb phrase ("Opens the file"), explain why rather
  than restating the code, write complete sentences with capitalization and punctuation, and
  write `TODO` in capitals with an owner or bug.
- Code and comments read as part of the upstream project: no references to oxgl, this
  repository or the bundles. Why the patch exists here goes in the README table.
- Check each patch's changed lines with the owning project's formatter before committing it
  (for example `clang-format --lines=<start>:<end>` with SwiftShader's `.clang-format`), and
  keep the patch to the minimum the change needs.
- A patch that only changes local configuration and is not meant for upstream (such as
  `swiftshader-high-precision-filtering.patch`) says so in its README row.

## Testing on Linux arm64

- When a check must run on Linux arm64 and the host is something else, Docker can be used: an
  arm64 host runs `linux/arm64` containers natively, for example
  `docker run --rm --platform linux/arm64 -v "$PWD":/src -w /src ubuntu:24.04 …`.
- Don't substitute another platform's result for a Linux arm64 one: ANGLE's backends differ
  between platforms.

## Correct, simple and fast enough is the bar

Designs, code and reviews all aim at the same three things: behaviour that is correct in the
conditions the system actually meets, code no more complex than that behaviour needs, and no
wildly wasteful work. The behaviour asked for is itself open to question when a simpler one
would serve. Surviving rare infrastructure failure is not a goal. A reviewer does not ask for
handling of it, and machinery added only for it is complexity to remove.

- **Correct means correct in normal operation.** Normal operation includes every platform and
  input the recipe supports and the retries the workflows make themselves. A defect there is
  always in scope.
- **A rare failure matters only when it does visible, lasting damage.** A rare failure is one
  that real use seldom produces: a runner that dies mid-build, a download that fails once, a
  GitHub outage. It is in scope only when it silently publishes a wrong or corrupt bundle, or
  leaves state that cannot be seen or repaired, and then the fix is the simplest one that
  prevents that damage. A failed run that is retried, a cache that empties or a delay is
  accepted and needs no handling.
- **Cheap handling of a rare error is welcome.** Handling one is fine when it stays inside the
  code path that already exists and adds no mechanism, stored field or new failure mode:
  checking a result the code already gets, or choosing a safer order for two steps it already
  takes. A reviewer neither asks for such handling nor flags it for removal.
- **Complexity is a cost the finding must pay for.** A fix that adds a mechanism or a new
  failure mode has to prevent damage that is likely or severe. Weigh a trigger by how often
  real use produces it, never by whether it can happen at all.
- **Inefficient means wildly inefficient.** In scope is work that is wasteful by an order of
  magnitude, such as rebuilding what could be reused or downloading the same thing per step. A
  constant-factor saving nobody would notice is below the bar.
- **A simpler design is worth a small change to the requirement.** When a requirement drives
  much of the complexity and a nearby one would serve the same purpose with far less, say so
  and name what the user gives up. This is pushback, never a unilateral change: the user
  decides.
- **Security and supply-chain integrity sit outside this bar.** Unverified downloads, unpinned
  actions or inputs, leaked credentials and anything that could alter a published bundle are
  surfaced however unlikely the trigger.
- **What falls below the bar is left out.** A reviewer does not report it, and a design adds
  no machinery for it.
