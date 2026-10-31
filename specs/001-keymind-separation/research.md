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

## R2. Does a disabled workflow stay disabled after its file changes? — Unverified

Expected: GitHub keeps the "disabled manually" state per workflow, but this is not confirmed here. **Decision**: verify on a throwaway repository (disable, push a change to the file, list state) before Phase B step 5, and re-check after the first real Keymind merge.
**Fallback if it does not hold**: leave the workflow enabled but not required (it triggers on every PR regardless and costs build minutes), or as a last resort carry a one-line guard in the file (a Keymind-file edit).

## R3. Why the 1.18.0.1 rail regression was not caught — Read

- Keymind's `test` job does run the policy fixture (`test_rak_gps_power.py`, step near line 885), but the fixture exercises the policy class alone.
- No test models the **quake image configuration** (`MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL`, default mode `gps-only`) and asserts the 3V3_S rail stays on. So the suite passed while the image dropped the sensors from telemetry.

**Decision**: add `test/test_quake_rail_default.py` (our file) that compiles the policy fixture with the quake flag, in the default `gps-only` mode, and asserts the rail is enabled, plus the inverse for the stock build. This is the single most valuable test in the new check.

## R4. Version ordering on the update path — Read (partly)

- `OtaFormat.h`: `ota_trusted_auto_version_allows(running, candidate)` is true only when both are non-zero and `candidate > running`, as unsigned 32-bit values of the packed version `MAJOR<<24 | MINOR<<16 | PATCH<<8 | pre`.
- Therefore `2.0.0.0` (0x02000000) is accepted as an upgrade over `1.18.0.2` (0x01120002).
- Not yet read: whether manual `ota install` or the flasher catalog validator applies its own ordering rule (earlier observation: the apps validator rejects repeated versions); how `ver` could report the Keymind base release.

**Decision**: candidate scheme `2.x.y.z`; the verification tasks in Phase E gate the first release.
**Alternatives**: keep `1.18.x.y` and add 100 to the last field (stays inside Keymind's space, so collisions remain possible); letter or fifth-number suffixes (rejected earlier: the 4-byte packing ignores them and the release workflow would skip the tag).

## R5. Changing required checks — Read (GitHub behaviour)

Branch protection names checks by their job/context name. `next` and `main` currently require exactly `test`. A check from a workflow skipped by a path filter never reports and stays pending, which blocks the merge; this is why `quake-repeater-release.yml` (path-filtered) cannot be the required check and a new unfiltered workflow is needed.

**Decision**: `quake-ci.yml` with a single aggregate job `quake-ci`, no workflow-level `paths:`.

## R6. Running Keymind's suite on Keymind merges — Read

`run-unit-tests.yml` triggers on `push` (main, master, keymindCascade), `pull_request` (all branches, no filter) and `workflow_dispatch`. A disabled workflow cannot be dispatched or triggered. **Decision**: a runbook that enables it for the duration of the merge PR and disables it again afterwards (cheap, reversible, no file edits). **Alternative**: a wrapper workflow of ours that dispatches it; rejected as extra moving parts for a once-per-release event.

## R7. Inherited automation — Read

Triggers on our branches: `run-unit-tests.yml` (push main, every PR) and `github-pages.yml` (push main, publishes Keymind's mkdocs site to `gh-pages`) are the two that act on us. The others (`build-companion`, `build-observer*`, `build-repeater`, `build-room-server`, `check-mqtt-preset-parity`) trigger only on tags or branches we do not use. `pr-build-check.yml` targets `main`/`dev` PRs with a path filter. Whether `github-pages.yml` currently succeeds or what it publishes has not been checked.

## Open questions carried into tasks

1. R2: disabled-state persistence (verify before cut-over).
2. R4: flasher validator and manual OTA ordering; `ver` base-version reporting.
3. `pr-build-check.yml`: decide disable vs. keep after reading what it builds (it may duplicate `quake-ci`).
4. Whether `github-pages.yml` has been publishing wrong content (check `gh-pages` before disabling).
