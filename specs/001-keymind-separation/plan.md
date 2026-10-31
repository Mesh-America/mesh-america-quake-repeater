# Implementation Plan: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Branch**: `spec/keymind-separation` | **Date**: 2026-10-30 (revised after two rounds of hostile review, see [review.md](review.md)) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-keymind-separation/spec.md`. Tasks are tracked in Beads (`bd`, prefix `qr`), not in a `tasks.md`.

## Summary

Make our own fast check the gate, keep Keymind's full suite for the moment it matters (a Keymind merge), and stop confusing our version numbers with Keymind's. Every step is ordered by merge cost, cheapest first, and no Keymind workflow file is edited.

| Phase | What changes | Where | Cost at next Keymind merge |
|-------|--------------|-------|----------------------------|
| A | New `quake-ci.yml`; a rail-hold test driven by the real build definitions; version-consistency and ordering checks; a stock smoke build; release workflow made to depend on the same checks | new files, plus our own `quake-repeater-release.yml` | none |
| B | Cut-over: land, observe, add, remove, disable, then the strict rules | repository settings | none |
| C | Keymind-merge runbook; revert our `if: false` edit inside the first merge window | one existing file reverted to Keymind's text | removes a conflict site |
| D | Workflow inventory plus a drift-check script | new files | none |
| E | Version scheme 2.x; `ver` shows the Keymind base release | variant file, our own `MyMeshQuake.cpp`, apps repo | low |
| F | Seam inventory; consolidation only if trial merges justify it | Keymind code files | can add as much as it removes |

A to D answer the three costs in the spec. E and F can wait.

## Technical Context

**Language/Version**: GitHub Actions YAML, Python 3.13, C++ (host `g++` for the policy fixture), PlatformIO.

**Primary Dependencies**: `pio run -e MeshAmerica_Quake_Repeater_RAK3401` and `..._RAK4631`; a stock RAK4631 smoke build; `scripts/quake_release_manifest.py`; `gh` CLI and GraphQL for settings.

**Storage**: N/A. State lives in repository settings and in Beads.

**Testing**: `test/test_quake_release_manifest.py`; new `test/test_quake_rail_default.py`; `pio test -e native` for four named suites (`test_d7s`, `test_d7s_wire`, `test_seismic_alert`, `test_clock_floor`); a short list of Keymind tests for shared code (decided in tasks; candidates `test_rak_gps_power.py`, `test_rak_shutdown_power.py`, `test_rak3401_onboard_radio.py`).

**Target Platform**: GitHub-hosted `ubuntu-latest`; nRF52840 firmware (RAK3401, RAK4631).

**Performance Goals**: required check at or under 15 minutes (p90 over the last ten runs, cold cache). Measured so far: our release workflow builds both images in 2 to 3 minutes on PRs (6 on `main`), "Build firmware" about 2 to 2.5 minutes. Not yet measured: the native tests and the shared-code Keymind tests. Keymind's own `pio test -e native` step took about 337 seconds for roughly 114 suites; ours runs four.

**Constraints**: never edit a Keymind workflow file; each settings change approved by the owner and reversible; the required check never pending and never passing on a failed dependency; release flow and flasher catalog pins (tag `quake-vX.Y.Z.W`) keep working; no mesh/internet path.

**Scale/Scope**: 2 images, 2 protected branches, 15 workflow files (2 ours today, 3 with `quake-ci.yml`) plus 2 default-setup checks, 11 modified Keymind files.

## Constitution Check

`.specify/memory/constitution.md` is still the unfilled template, so there are no project principles to gate on. The binding constraints are the maintainer rules carried into the spec: Keymind merges stay easy; Keymind workflow files untouched; every commit on `main` goes back into `next`; no internet gateway for the mesh. The design respects all four. **Gate: pass.** Recommendation: fill in the constitution from those rules.

## Project Structure

### Documentation (this feature)

```text
specs/001-keymind-separation/
├── plan.md, research.md, data-model.md, quickstart.md
├── review.md            # both review rounds and how each finding was handled
├── contracts/ci-and-settings.md
└── checklists/requirements.md
```
Tasks: Beads, `bd list` in the repository root.

### Source Code (repository root)

```text
.github/workflows/
├── quake-ci.yml                  # NEW (A): required check; also workflow_call
├── quake-repeater-release.yml    # ours; release job now depends on quake-ci
├── quake-docs-pages.yml          # ours
└── run-unit-tests.yml            # Keymind's; our `if: false` reverted in C; disabled in settings
.github/WORKFLOWS.md              # NEW (D): inventory
.github/SEAMS.md                  # NEW (F): seam inventory
scripts/check_workflow_inventory.py   # NEW (D)
scripts/check_quake_version.py        # NEW (A/E): numeric ordering, base-release check
test/test_quake_rail_default.py       # NEW (A)
variants/meshamerica_quake/platformio.ini   # shared [quake_version] section (E)
apps repo: quake-repeater/catalog/catalog.source.json   # previousReleases at the first 2.x release (E)
```

**Structure Decision**: new automation is additive; everything else is a repository setting or a revert. Keymind-file edits would only come from Phase F.

## Phase A: our fast check

1. **Triggers**: `pull_request` to `main` and `next`, `push` to `main` and `next`, and `workflow_call` so the release workflow reuses the same jobs. **No workflow-level `paths:` filter.**
2. **Job structure**: job `tests`, job `build` (matrix of both images, plus one stock smoke build), job `release-metadata` (needs `build`; reads the built manifests), and a final non-matrix job with id `quake-ci` and **no `name:`**, `needs: [tests, build, release-metadata]`, `if: ${{ always() }}`, whose single step fails unless every `needs.*.result` is `success`. No `concurrency: cancel-in-progress` on it. Only `quake-ci` is ever a required context.
3. **`tests` job**:
   - `test_quake_release_manifest.py`.
   - **Four named native suites** run with `pio test -e native -f test_d7s -f test_d7s_wire -f test_seismic_alert -f test_clock_floor` and a machine-readable report; the step fails unless exactly four suites passed. Open: whether to give ourselves a small `native_quake` environment, because `native` compiles about 40 Keymind sources and an unrelated upstream break would turn our check red (decided in tasks after measuring).
   - Shared-code Keymind tests chosen in tasks (the short list above).
4. **`test_quake_rail_default.py`** (replaces the first design, which the second review showed was self-referential and could not run on real flags):
   - Resolve each quake environment's `build_flags` with PlatformIO's own config resolution, then **whitelist only the defines the rail policy reads**: `RAK_3401`, `RAK_4631`, `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL`, `ETHERNET_ENABLED`, `ETHERNET_USE_RAK13800`, `RAK4631_COMBINED_ETHERNET`. (The policy tests `defined()`, so even `=0` counts as a hold.)
   - Compile `test/fixtures/wisblock_shared_power_policy.cpp` with those defines and `-DEXPECTED_COMPILE_HOLDS=<value from a table in the test>`: **16 (`SensorPower`) for the RAK4631 image, 1 (`RadioPower`) for the RAK3401 image**. The fixture's `static_assert` goes red if the real setting disappears or changes. No anchors into Keymind source.
   - A lifecycle-level assertion (the rail pin stays high under `gps-only`) is optional and would be a new fixture of ours; it must not edit Keymind's `rak_gps_power.cpp`.
5. **`release-metadata` job**: from the built `manifest*.json` files (not by regexing `platformio.ini`, which would miss the fallback to the header's `v1.18.0`): both images carry the same version; on a pull request whose version differs from the merge base, it is **numerically** greater than the highest existing `quake-v*` tag (checkout with full history and tags); on `push` and tag events the rule is "not lower than the highest tag"; merge-back pull requests (head `merge/main-into-next-*`) are exempt.
6. **Keymind-merge guard**: for a head ref matching `merge/keymind-*`, a step fails unless a completed `run-unit-tests` run exists for the head SHA (any conclusion; the verdict is the owner's). Needs `actions: read` permission.
7. **Stock smoke build**: one plain `pio run` of a stock RAK4631 repeater environment with the earthquake sensor off (closest sibling to the quake image: `RAK_4631_repeater_lora_ota_no_external_sensors`; chosen in tasks), because our hooks sit in shared headers. Optionally a stock RAK3401 build for `RAK3401Board.cpp`. Keymind's own smoke job uses `build.sh` with two profiles and took 13 minutes, so not that.
8. **Release workflow** (`quake-repeater-release.yml`, ours): the `release` job calls `quake-ci` (via `workflow_call`) and `needs` it, so a push to `main` and a tag push publish only after the same checks pass; a guard step fails the release unless the tagged commit is reachable from `main`. Decide in tasks whether to share builds between the two workflows (today they build the same images twice) after measuring cold-cache time.
9. **Fault drill** (SC-003): F1 to F8 on scratch branches, each must turn `quake-ci` red; plus fewer than four suites running; plus a docs-only and a workflow-only PR going green; plus a YAML syntax error to see that it hangs rather than fails (and that cut-over step 2 observation catches it).
10. Run `quake-ci` beside Keymind's `test` for at least three PRs before Phase B.

## Phase B: cut-over (repository settings; owner approves each step)

Order: **land, observe, add, remove, disable, tighten**. Exact calls are in [contracts/ci-and-settings.md](contracts/ci-and-settings.md). Highlights:

1. Land `quake-ci.yml` on `next`; push to or reopen any older open PR.
2. Observe on at least three PRs, including docs-only and workflow-only.
3. Add `quake-ci` (app id 15368) to the required checks on `next`, keeping `test`. On `main`, only after a release has put the workflow file on `main`.
4. Remove `test`; disable `run-unit-tests.yml`.
5. Create the tag rule for `quake-v*`.
6. Last: `strict` on, force-push on `next` blocked, `enforce_admins` on. Force-push has no narrow REST endpoint, so use GraphQL `updateBranchProtectionRule` (field names verified by a read-only query first) or an explicit, diffed full PUT body.
7. Write the release ritual (below) into the docs before step 6.
8. Rollback restores every setting changed (checks, `strict`, force-push, `enforce_admins`, tag rule). Rolling `test` back in is valid only before Phase C reverts our skip (otherwise the stock-app step fails).
9. Break-glass: with `enforce_admins` on there is no merge-time bypass; the owner removes `quake-ci` from the required list by settings change, merges, notes it on the PR, and restores it straight away. A broken `quake-ci.yml` is fixed by a PR running its own corrected copy (not by a syntax error, which produces no check).

**Release ritual after cut-over** (needed because `strict` and `enforce_admins` are on):
1. PRs into `next`; merge commits.
2. Release PR `next` into `main`, **merge commit only** (a squash or rebase would leave `next` permanently non-descendant). Repository merge-method settings: owner decision in the contract.
3. After the release lands, `main` is one commit ahead of `next`. **Merge-back is a pull request**: branch `merge/main-into-next-<n>` from `next`, merge `main` into it, open a PR into `next`, wait for `quake-ci`, merge. Never a PR with head `main`. Direct pushes are rejected once administrators are bound.
4. The next release PR is blocked until step 3 has landed.
5. Update the standing merge-back memory note with this method when the cut-over happens.

## Phase C: Keymind-merge runbook

Triggers of `run-unit-tests.yml`: `pull_request` (no filter), `push` to `main`/`master`/`keymindCascade`, `workflow_dispatch`.
1. Branch `merge/keymind-<release>` from `next`; resolve conflicts (a conflicted PR starts no `pull_request` workflows).
2. `gh workflow enable run-unit-tests.yml`, then **push or reopen** the PR. Dispatching on the branch is a fallback only: it tests the branch tip, not the merge ref against `next`.
3. A failure counts as "unrelated" only if the same step fails on the pristine Keymind tag; the verdict is recorded on the PR. The Quake check's Keymind-merge guard (Phase A item 6) will not pass until a completed run exists.
4. Revert our `if: ${{ false }}` edit **inside the first merge window**, never before (reverting while `test` is required blocks every PR). Afterwards the stock-app step is red by design (upstream has not fixed it).
5. Merge, `gh workflow disable run-unit-tests.yml`, run the inventory check in window mode, record time and conflict list.

## Phase D: inventory and drift check

`.github/WORKFLOWS.md` lists every workflow (file-backed and default-setup). `scripts/check_workflow_inventory.py` compares the live `gh workflow list --all` and the files on disk with the inventory, has a "window" mode for deliberate enables, and runs in each merge window and manually. It needs `actions: read`. It does not run from `quake-ci` on a schedule.

## Phase E: version scheme

Verified: 1.18.0.2 packs to 0x01120002 and 2.0.0.0 to 0x02000000; the build tooling, tag derivation and flasher accept 2.x (the flasher only checks that versions are distinct and `previousReleases` order is by hand). The only numeric ordering on devices is the trusted auto-install gate, which is off by default and needs signed packages. Real update paths (USB/Bluetooth DFU, manual on-air install) have no version gate. So the case for 2.x is avoiding human confusion, and it assumes Keymind stays on major 1.

1. Factor `FIRMWARE_VERSION` and a new `KEYMIND_BASE_VERSION` into one shared section of `variants/meshamerica_quake/platformio.ini` so they stop being hand-copied per environment.
2. The `ver` reply is built in our own `examples/simple_repeater/MyMeshQuake.cpp:280`; the owner-info reply (`MyMesh.cpp:997`, a Keymind file) also prints product and version. Decide whether owner-info changes (that would be a seam) or stays, but the two MUST NOT contradict each other (FR-014). Real consumers of the bare version: MQTT bridge, SNMP, WebConfig, management reports, update identity, boot banner and UI. No advert or telemetry code reads it.
3. Check `KEYMIND_BASE_VERSION` against the highest Keymind release tag merged into the branch (`git tag --merged HEAD`, full fetch in CI).
4. Keep the `Quake Repeater <version>` prefix that the flasher's regex (`^(?:Mesh America )?Quake Repeater\s+(v?\d+(?:\.\d+){1,3})\b`) matches, and fix the flasher's stale `(Build: …)` comment.
5. Open question to close: do official apps change behaviour on a repeater major version of 2 (task).
6. Apps repo, at the first 2.x release: pin the new tag and put 1.18.0.2 first in `previousReleases` for all three variants (lists differ in length). Catalog verification uses a fixture or pre-release first, because the build downloads real release assets.
7. Hardware: USB/Bluetooth DFU and manual `ota install` from 1.18.0.2; `ver` shows both versions.
8. Ordering guard for the release lives in the `release-metadata` job (the release workflow only asks whether the tag exists and always passes `--latest`).

## Phase F: seams

`MyMesh.cpp` has 8 separate hunks, `MyMesh.h` 4 (including an include and the product-name define), `WisBlockSharedPowerPolicy.h` 3, and four of our lines edit existing Keymind lines, so one block per file is unachievable. Upstream rewrote about 700 lines of `MyMesh.cpp`/`.h` in six days and the current layout merged with 0 conflicts. So F starts with `.github/SEAMS.md` (file, purpose, additive or edit, upstream churn, reference for the churn count) and consolidates only where a trial merge shows a recurring conflict. Offering generic hooks (sensor-rail hold, seismic reading) to Keymind remains the maintainer's decision. Note the churn figures in earlier drafts (332, 96, 67, 38, 37, 14) did not reproduce exactly in a different clone (361, 102, 83, 38, 51, 22); the inventory must state its reference and date.

## Risks

| Risk | Mitigation |
|------|------------|
| Aggregate check skipped or passing on a failed dependency | separate fail-closed job; F8 drill |
| Rail test passes with the flag deleted | table-driven expected masks with the real defines; F2 and F3 drills |
| Required check stuck pending (syntax error, renamed job) | no path filter, no job `name:`, observed before required, break-glass |
| Merge-back rejected once admins are bound | merge-back becomes a PR; ritual documented before cut-over |
| Release blocked by `strict` until merge-back lands | documented in the ritual; accepted |
| Tag push bypasses branch rules | tag rule; release depends on the same checks; tagged commit reachable from `main` |
| Merge cost is episodic, dominated by history rewrites (1.18.0.1 had 4 conflicting files and a rewritten base) | trial merge before each real merge; seam inventory; A to D do not change this cost |
| New or renamed upstream workflow arrives enabled | inventory drift check in each merge window |
| Unrelated Keymind break turns our native tests red | decide on a `native_quake` environment after measuring |
| A pull request can edit its own check | accepted and recorded (FR-017); owner reviews `.github/**` diffs |
| 2.x breaks release or flasher tooling | Phase E verification before the first release |

## Complexity Tracking

No constitution violations to justify.
