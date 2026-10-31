# Research: Keymind separation

Status of each finding: **Measured** (observed in this repository), **Read** (from source files), **Unverified** (must be checked by a task before relying on it).

## R1. Where the time goes — Measured

Run times from the repository's own history (`gh run list`):

| Workflow | Typical run | Notes |
|----------|-------------|-------|
| `quake-repeater-release.yml` (builds both images, verifies, writes manifests) | 2 to 3 min on PRs, up to 6 min on `main` | already ours |
| `run-unit-tests.yml`, job `test` (57 serial steps) | 57 to 94 min | runs on every PR and every push to `main`; one push to `main` failed at 94 min |

**Decision**: our check is the existing build plus the tests that cover our code; target 15 minutes with margin.
**Alternatives rejected**: trimming `test` to the nRF52 steps (edits a Keymind workflow file, conflicts at every merge, and was declined earlier); parallelising it (same).

## R2. Does a disabled workflow stay disabled after its file changes? — Partly measured

Several inherited workflows were disabled on 2026-10-03; `build-repeater-firmwares.yml` was changed by a later merge (commit cc4bcb9ca, 2026-10-05) and is still `disabled_manually`. State is keyed by workflow ID, so an **added or renamed** upstream workflow file arrives enabled, and a deleted-and-re-added one is new. **Decision**: re-check after the next real merge, and run the inventory drift check (Phase D) in every merge window.
**Fallback if a workflow comes back**: disable it again; the drift check flags it.

## R3. Why the 1.18.0.1 rail regression was not caught, and how the new test avoids the same blind spot

- Keymind's `test` job runs `test_rak_gps_power.py` (step near line 885). The lifecycle harness (`test/fixtures/rak_gps_power.cpp`) defines `compile_held = wisBlockCompileRailHolds() != 0` and compares every result to it, so removing the hold flag flips both sides and every scenario still passes. It also extracts function bodies from `EnvironmentSensorManager.cpp` with hard-coded anchors.
- The real quake `build_flags` cannot be passed to the host compiler wholesale: they include `${rak4631.build_flags}`, quoted strings, `-include`, `-U` flags and `ENV_INCLUDE_D7S`, which changes headers the stub fixtures were not written for.

**Decision**: resolve each quake environment's flags with PlatformIO's config, whitelist only the defines the policy reads (`RAK_3401`, `RAK_4631`, `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL`, `ETHERNET_ENABLED`, `ETHERNET_USE_RAK13800`, `RAK4631_COMBINED_ETHERNET`), and compile `test/fixtures/wisblock_shared_power_policy.cpp` with `-DEXPECTED_COMPILE_HOLDS` taken from a table in the test (RAK4631 image 16 = `SensorPower`; RAK3401 image 1 = `RadioPower`). The fixture's `static_assert` goes red when the real setting changes. This needs no anchors in Keymind source. **Not yet verified**: PlatformIO config resolution in CI (no `pio` on the review machine), so the first task builds this test and proves it red.

## R4. Version ordering on the update path — Read (partly)

- `OtaFormat.h`: `ota_trusted_auto_version_allows(running, candidate)` is true only when both are non-zero and `candidate > running`, as unsigned 32-bit values of the packed version `MAJOR<<24 | MINOR<<16 | PATCH<<8 | pre`.
- Therefore `2.0.0.0` (0x02000000) is accepted as an upgrade over `1.18.0.2` (0x01120002).
- Read since: manual `ota install` has no version gate; the bootloader continuity gate applies to bootloader packages only; the flasher validator and builder only require distinct versions (the order of `previousReleases` is by hand); the release tooling derives the tag from the packed image version. The trusted auto-install gate is off by default and needs signed packages, which Quake does not use, so Quake's real update paths never consult version order.
- Keymind's `mesh-america/*` and `scripts/generate_mesh_america_release.py` were flagged by a reviewer but are out of scope: per the owner they are how Keymind reaches the Mesh America Device Configurator app and are unrelated to Quake releases.

**Decision**: 2.x is about avoiding human confusion, not preventing a mechanical collision (OTA target ID, tag prefix and repository already differ). Candidate `2.0.0.0`; Phase E verification gates the first release.
**Alternatives**: keep `1.18.x.y` and add 100 to the last field (stays inside Keymind's space, so collisions remain possible); letter or fifth-number suffixes (rejected earlier: the 4-byte packing ignores them and the release workflow would skip the tag).

## R5. Changing required checks — Read (GitHub behaviour)

Branch protection names checks by their job/context name. `next` and `main` currently require exactly `test`. A check from a workflow skipped by a path filter never reports and stays pending, which blocks the merge; this is why `quake-repeater-release.yml` (path-filtered) cannot be the required check and a new unfiltered workflow is needed.

**Decision**: `quake-ci.yml` with a single aggregate job `quake-ci`, no workflow-level `paths:`.

## R6. Running Keymind's suite on Keymind merges — Read

`run-unit-tests.yml` triggers on `push` (main, master, keymindCascade), `pull_request` (all branches, no filter) and `workflow_dispatch`. A disabled workflow cannot be dispatched or triggered. **Decision**: a runbook that enables it for the duration of the merge PR and disables it again afterwards (cheap, reversible, no file edits). **Alternative**: a wrapper workflow of ours that dispatches it; rejected as extra moving parts for a once-per-release event.

## R7. Inherited automation — Read

Measured with `gh workflow list --all`: `github-pages`, `pr-build-check`, `sync-flasher-content`, `stale-bot`, the observer, companion, repeater and room-server builds, and `check-mqtt-preset-parity` have been `disabled_manually` since 2026-10-03. Active: `run-unit-tests`, `firmware-builder` (`workflow_call` only), our two Quake workflows, and the default-setup code scanning and dependency graph. Our live documentation site is deployed by `quake-docs-pages.yml` (Pages build type: workflow); the `gh-pages` branch was last written on 2026-10-03 and is not what is served. So only `run-unit-tests.yml` acts on us.

## R8. Gates around the branch rules — Measured / Read

- Merge-back (`chore: merge main back into next`) has been a direct push of a merge commit (no PR; e.g. `83b1862c0`, six or more times). With `enforce_admins` on and a required PR, a direct push is rejected, so merge-back becomes a PR (contract, release ritual).
- With `strict` on, `next` is one commit behind `main` after every release, so the next release PR is blocked until the merge-back PR lands; every other open PR needs refreshing after each merge. Repository merge methods currently allow squash and rebase, which would leave `next` non-descendant of `main`.
- A `quake-v*` tag push publishes a release with no PR; the release job depends only on its own `build`, and there are no rulesets. Without a dependency on the same checks and a tagged-commit-on-`main` guard, the branch rules are bypassable. A tag rule restricting creation was considered and dropped: the release workflow creates its own tag with `GITHUB_TOKEN` (`gh release create`, `quake-repeater-release.yml`), so an owner-only rule would block it unless the Actions app were a bypass actor, and agents run as the owner so identity does not separate them.
- On a push to `main`, the release workflow and the (future) `quake-ci` run in parallel; the release must `needs` the checks.
- GraphQL (read-only, 2026-10-30): the rule IDs and fields are listed in the contract; `updateBranchProtectionRule` accepts `allowsForcePushes`, `isAdminEnforced`, `requiresStrictStatusChecks`, `requiredStatusChecks`.

## R9. Suite counting and cost of `native` — Read

All four earthquake suite directories exist (`test_d7s`, `test_d7s_wire`, `test_seismic_alert`, `test_clock_floor`); `[env:native]` compiles `D7S.cpp`, `SeismicAlert.cpp`, `ClockFloor.cpp` into the test build and ignores only three other suites. Unfiltered `pio test -e native` runs about 114 suites (Keymind's step took about 337 s) and compiles about 40 Keymind sources. Running only four with `-f` is cheaper but still compiles those sources, so an unrelated upstream break can turn our check red. Open: exit status of an unmatched filter, the report flag, and whether a small `native_quake` environment is worth having. The task measures them.

## Open questions carried into tasks

1. R2: disabled-state persistence (verify before cut-over).
2. R4: flasher validator and manual OTA ordering; `ver` base-version reporting.
3. Cold-cache run time of `quake-ci` and of `pio test -e native`; whether `pio test` with an unmatched filter exits 0.
4. Whether official apps feature-gate on the repeater version string (major 1 to 2).
5. (none further; the Device Configurator tooling is out of scope.)
