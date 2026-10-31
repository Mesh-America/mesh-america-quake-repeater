# Implementation Plan: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Branch**: `spec/keymind-separation` | **Date**: 2026-10-30 (revised after hostile review, see [review.md](review.md)) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-keymind-separation/spec.md`

## Summary

Make our own fast check the gate, keep Keymind's full suite for the moment it matters (a Keymind merge), and stop confusing our version numbers with Keymind's. Every step is ordered by merge cost, cheapest first, and nothing edits a Keymind workflow file.

| Phase | What changes | Where | Cost at next Keymind merge |
|-------|--------------|-------|----------------------------|
| A | New `quake-ci.yml`, a rail-hold test that reads the real build definitions, a version-consistency check, a stock-build smoke | new files only | none |
| B | Cut-over: observe, then require `quake-ci`, then drop `test`, then disable `run-unit-tests.yml` | repository settings only | none |
| C | Keymind-merge runbook; revert our `if: false` edit inside the first merge window | one existing file reverted to Keymind's text | removes one conflict site |
| D | Workflow inventory plus a drift-check script | new files | none |
| E | Version scheme and the `ver` base-release string | variant file, our own `MyMeshQuake.cpp`, apps repo | low |
| F | Seam inventory; minimal consolidation only if trial merges justify it | Keymind code files | can add as much as it removes |

A to D answer the three costs in the spec. E and F are separable and can wait.

## Technical Context

**Language/Version**: GitHub Actions YAML, Python 3.13, C++ (host `g++` for the policy fixtures), PlatformIO.

**Primary Dependencies**: `pio run -e MeshAmerica_Quake_Repeater_RAK3401` and `..._RAK4631`; a stock RAK4631 repeater environment for the smoke build; `scripts/quake_release_manifest.py`; `gh` CLI for settings.

**Storage**: N/A. State lives in repository settings.

**Testing**: `test/test_quake_release_manifest.py`; `test/test_rak_gps_power.py` and its lifecycle harness; `pio test -e native` for **four** suites: `test_d7s`, `test_d7s_wire`, `test_seismic_alert`, `test_clock_floor`; new `test/test_quake_rail_default.py`.

**Target Platform**: GitHub-hosted `ubuntu-latest`; nRF52840 firmware (RAK3401, RAK4631).

**Project Type**: firmware repository CI, release and build metadata.

**Performance Goals**: required check at or under 15 minutes (90th percentile, cold cache). Baseline: the release workflow builds both images in 2 to 6 minutes warm. Cold-cache time and test time are not yet measured.

**Constraints**: never edit a Keymind workflow file; each settings change approved by the owner and reversible; the required check never pending and never passes on a failed dependency; release flow and flasher catalog pins (tag `quake-vX.Y.Z.W`) keep working; no mesh/internet path.

**Scale/Scope**: 2 images, 2 protected branches, 15 workflow files (2 ours today, 3 with `quake-ci.yml`) plus 2 active default-setup checks (code scanning, dependency graph), 11 modified Keymind files.

## Constitution Check

`.specify/memory/constitution.md` is still the unfilled template, so there are no project principles to gate on. The binding constraints are the four maintainer rules carried into the spec: Keymind merges stay easy; Keymind workflow files untouched; every commit on `main` merged back into `next`; no internet gateway for the mesh. The design respects all four. **Gate: pass.** Recommendation: fill in the constitution from those rules.

## Project Structure

### Documentation (this feature)

```text
specs/001-keymind-separation/
├── plan.md, research.md, data-model.md, quickstart.md
├── review.md            # hostile review findings and how each was handled
├── contracts/ci-and-settings.md
├── checklists/requirements.md
└── tasks.md             # next step (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
.github/workflows/
├── quake-ci.yml                  # NEW (A): required check
├── quake-repeater-release.yml    # ours; path-filtered on PRs; never required
├── quake-docs-pages.yml          # ours
└── run-unit-tests.yml            # Keymind's; our `if: false` reverted in C; disabled in settings
.github/WORKFLOWS.md              # NEW (D): inventory (not under docs/, which mkdocs may publish)
scripts/check_workflow_inventory.py   # NEW (D): compares `gh workflow list --all` with the inventory
test/test_quake_rail_default.py       # NEW (A)
variants/meshamerica_quake/platformio.ini   # version, KEYMIND_BASE_VERSION (E)
apps repo: quake-repeater/catalog/catalog.source.json   # previousReleases edit at the first 2.x release (E)
```

**Structure Decision**: new automation is additive; everything else is a repository setting or a revert. The only Keymind-file edits would be whatever F justifies.

## Phase A: our fast check

1. **Triggers**: `pull_request` to `main` and `next`, and `push` to `next` and `main`, with **no workflow-level `paths:` filter**. Tag-triggered releases call the same tests (a reusable workflow, or the same steps) so a tag-only release is also gated (FR-018).
2. **Job structure** (fixes the review's blocker): job `tests` (rail, native suites, manifest, version consistency) and job `build` (matrix of the two images plus one stock RAK4631 smoke build) both run first. A separate non-matrix job `quake-ci` has `needs: [tests, build]`, `if: ${{ always() }}`, and one step that fails unless every `needs.*.result` equals `success`. No `concurrency: cancel-in-progress` on it (a cancelled run reports as a failure). The required context is exactly `quake-ci`.
3. **Tests job contents**:
   - `test_quake_release_manifest.py`.
   - `test_rak_gps_power.py` (the stock policy fixture and lifecycle harness).
   - `pio test -e native` for the four suites, with a check that the number of suites that ran equals four (a filter that matches nothing must fail).
   - `test_quake_rail_default.py` (below).
   - **Version consistency**: both `FIRMWARE_VERSION` values in `variants/meshamerica_quake/platformio.ini` are equal and, on a **pull request that changes the version**, greater than the highest existing `quake-v*` tag. The ordering part runs on `pull_request` only: on a push to `main` the release job creates the tag for that same push, so the version would equal the newest tag and the check would fail. This catches today's hand-synchronised mismatch before the merge to `main` instead of after.
4. **`test_quake_rail_default.py`** (fixes the review's blocker on the rail test): it **reads the `build_flags` of each real quake environment** from `variants/meshamerica_quake/platformio.ini` (by parsing the file or `pio project config`), then feeds those defines into the existing lifecycle harness under the default `gps-only` mode. It asserts the RAK4631 expectation (sensor rail held, so the rail stays enabled and the sensors stay in telemetry) and states and asserts the RAK3401 expectation (radio-power hold only; its sensor path is unchanged by this work). Deleting `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL` from the real file turns it red. It depends on the harness's source anchors in Keymind's `EnvironmentSensorManager.cpp`; an anchor change after a Keymind merge is a known cost, recorded in the seam inventory.
5. **Stock smoke build**: one stock RAK4631 repeater environment (as in Keymind's own nRF52 sensor smoke job) built with the earthquake sensor off, because our hooks sit in shared headers (`SensorManager.h`) and a break there would otherwise appear only in a merge window and be blamed on Keymind.
6. **Build reuse**: `quake-repeater-release.yml` already builds both images; `quake-ci` builds them again. Decide in the task list between (a) accept the duplicate, (b) make the release workflow call a shared reusable build. Measure cold-cache time first.
7. **Prove it** on scratch branches: remove the rail hold; break the alert test; make the two versions differ; break one matrix leg. Each must turn `quake-ci` **red** (not skipped, not pending). Also a docs-only and a workflow-only PR must go green.
8. Run `quake-ci` beside Keymind's `test` for at least three PRs before Phase B.

## Phase B: cut-over (repository settings; owner approves each step)

Order is mandatory: **land, observe, add, remove, disable**. Details in [contracts/ci-and-settings.md](contracts/ci-and-settings.md).

1. Land `quake-ci.yml`. Make sure no open PR predates it (push or reopen any that do).
2. Observe `quake-ci` on at least three PRs including a docs-only one and a workflow-only one.
3. Add `quake-ci` to the required checks with the narrow endpoint, pinned to the GitHub Actions app, keeping `test`.
4. Remove `test` from the required checks.
5. Disable `run-unit-tests.yml` (the only inherited workflow still active). `github-pages.yml` and the rest are already disabled.
6. Owner decisions (recorded in the contract, all taken 2026-10-30): `enforce_admins` **on**, so administrators cannot merge around a failed `quake-ci`; force-push on `next` **blocked**; `strict` (up-to-date branch) **on**. Today both branches have `enforce_admins:false`, `strict:false`, no review requirement, and `next` allows force pushes. These are switched on as the **last** cut-over step, after `quake-ci` has gone green on every kind of PR.
7. Rollback: re-enable, then PATCH the saved `checks` array back (never replay the full protection JSON).
8. Break-glass (no merge-time bypass exists once `enforce_admins` is on): if `quake-ci` cannot run for a reason outside the repository, the owner removes it from the required list by settings change, merges, notes it on the PR, and restores it straight away. A broken `quake-ci.yml` is fixed by a PR that runs its own corrected copy.

## Phase C: Keymind-merge runbook

Triggers of `run-unit-tests.yml`: `pull_request` (no filter), `push` to `main`/`master`/`keymindCascade`, `workflow_dispatch`.

1. Create `merge/keymind-<release>` from `next`; resolve conflicts; keep the PR mergeable (a PR with conflicts does not start `pull_request` workflows).
2. `gh workflow enable run-unit-tests.yml`, then push or reopen the PR, or `gh workflow run run-unit-tests.yml --ref merge/keymind-<release>` (enabling alone does not run anything on an open PR).
3. Expect a red stock-app compatibility step if our `if: false` skip has been reverted (upstream has not fixed that test). A failure counts as "unrelated" only if the same step fails on the pristine Keymind tag; record the verdict in the PR before merging.
4. Revert our `if: ${{ false }}` edit inside the first merge window, not before: reverting while `test` is still required would block every PR. After a clean merge the file equals the Keymind tip's blob; against the old base it equals blob `59d00855`.
5. Merge, then `gh workflow disable run-unit-tests.yml`, then run the inventory check (D). While enabled, the suite also starts on other PRs; keep the window short.
6. Record the working time and conflict list (SC-005, SC-008).

## Phase D: inventory and drift check

`.github/WORKFLOWS.md` lists every workflow from `gh workflow list --all` (state, trigger, why), including the two default-setup jobs. `scripts/check_workflow_inventory.py` fails if the live list contains a workflow that is missing from the inventory or is enabled when the inventory says disabled. Run it in each Keymind merge window and from `quake-ci` on a schedule or manually.

## Phase E: version scheme

Verified: the packed value of 1.18.0.2 is 0x01120002 and of 2.0.0.0 is 0x02000000; build tooling, tag derivation and the flasher accept 2.x (the flasher only checks that versions are distinct, and `previousReleases` order is by hand). The only numeric ordering on devices is the trusted auto-install gate, which is off by default and needs signed packages, which Quake does not use. Real update paths (USB/Bluetooth DFU, manual on-air install) have no version gate.

Therefore the case for 2.x is **avoiding human confusion**, not a collision mechanism. Tasks:
1. (Dropped on the owner's word: Keymind's `mesh-america/*` tooling feeds Keymind into the Mesh America Device Configurator app and is unrelated to Quake releases.)
2. `KEYMIND_BASE_VERSION` macro in our variant file, used only in the `ver` text. The `ver` reply is built in our own `examples/simple_repeater/MyMeshQuake.cpp:280` (`FIRMWARE_PRODUCT` plus `getFirmwareVer()`), so this adds no seam in `MyMesh.cpp`/`.h`. The owner-info reply (`MyMesh.cpp:997`) also prints product and version; leave it unchanged, keeping the bare version for adverts, telemetry and bridges. CI check that it matches the last merged Keymind release. Keep a suffix after the version so the flasher's `ver` regex still matches.
3. Monotonicity check in `quake-ci` (Phase A item 3).
4. Apps repo: at the first 2.x release, pin the new tag and move 1.18.0.2 to the front of `previousReleases` for all three variants. FR-015 verification uses a fixture or pre-release because the catalog build downloads real release assets.
5. Test on hardware: USB/Bluetooth DFU and manual `ota install` from 1.18.0.2.
6. The release workflow has no ordering guard (it only asks whether the tag exists and always passes `--latest`); the monotonicity check in `quake-ci` is the guard.
Open owner decision: confirm 2.0.0.0, or choose another scheme (for example a high major).

## Phase F: seams

The review showed one block per file is not achievable: `MyMesh.cpp` has 8 separate hunks, `MyMesh.h` 4 (including an include and the product-name define), `WisBlockSharedPowerPolicy.h` 3, and four of our lines edit existing Keymind lines. Upstream rewrote about 700 lines of `MyMesh.cpp` and `.h` in six days and the current layout still merged with **0 conflicts**. Moving code could make conflicts worse. So Phase F is first an inventory, ranked by upstream churn (commits since 2026-10-01: `run-unit-tests.yml` 332, `MyMesh.cpp` 96, `MyMesh.h` 67, `mkdocs.yml` 38, `platformio.ini` 37, `EnvironmentSensorManager.cpp` 14, the rest under 7). Consolidate only where trial merges show a recurring conflict, keeping logic in our own files (`MyMeshQuake.cpp`, `D7S*`) and short `#if ENV_INCLUDE_D7S` hooks. Offering generic hooks (sensor-rail hold, seismic reading) to Keymind remains the maintainer's decision.

## Risks

| Risk | Mitigation |
|------|------------|
| Aggregate check skipped or passing on a failed dependency | separate fail-closed job; red-case tests in Phase A step 7 |
| Rail test passes with the flag deleted | test reads the real environment definition; proven red on a scratch branch |
| Required check stuck pending or broken | no path filter; observed before required; break-glass procedure |
| Bypass: admins, `strict:false`, force-push on `next`, tag-only release | owner decided: admins bound, `strict` on, force-push blocked; tag releases gated; the only way around the check is a visible settings change |
| Owner locked out by an untested check once `enforce_admins` is on | switched on last; rollback is `DELETE .../enforce_admins` |
| Keymind merge cost is episodic, dominated by history rewrites (the 1.18.0.1 merge had 4 conflicting files and a rewritten base) | trial merge before each real merge; seam inventory; none of A to D changes this cost |
| New or renamed upstream workflow arrives enabled | inventory drift check in each merge window |
| Stock builds break through shared headers | stock RAK4631 smoke build in `quake-ci` |
| 2.x breaks release or flasher tooling | Phase E verification before the first release |

## Complexity Tracking

No constitution violations to justify.
