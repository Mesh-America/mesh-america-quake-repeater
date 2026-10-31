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

## R3. Why the 1.18.0.1 rail regression was not caught — Read

- Keymind's `test` job runs `test_rak_gps_power.py` (step near line 885). The policy fixture only checks the compile-time hold mask against a value the test supplies; the `gps-only` rail behaviour lives in a lifecycle harness that extracts function bodies from `EnvironmentSensorManager.cpp` using hard-coded source anchors.
- Nothing reads the **real quake environment definition** (`variants/meshamerica_quake/platformio.ini`) and asserts the sensor rail stays on under the default `gps-only` mode. A test that passes the define itself stays green even if the define is deleted from the real file (a hostile reviewer pointed this out).

**Decision**: `test/test_quake_rail_default.py` (our file) parses each quake environment's `build_flags`, feeds those defines to the lifecycle harness under `gps-only`, and asserts the expected rail for each image. Cost: it shares the harness's source anchors in Keymind code, so an anchor change after a merge breaks it; the seam inventory records that.

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

## Open questions carried into tasks

1. R2: disabled-state persistence (verify before cut-over).
2. R4: flasher validator and manual OTA ordering; `ver` base-version reporting.
3. Cold-cache run time of `quake-ci` and of `pio test -e native`; whether `pio test` with an unmatched filter exits 0.
4. Whether official apps feature-gate on the repeater version string (major 1 to 2).
5. (none further; the Device Configurator tooling is out of scope.)
