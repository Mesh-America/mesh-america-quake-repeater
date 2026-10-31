# Implementation Plan: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Branch**: `spec/keymind-separation` | **Date**: 2026-10-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-keymind-separation/spec.md`

## Summary

Make our own fast check the gate, keep Keymind's full suite for the moment it matters (a Keymind merge), and stop sharing a version space with Keymind. Every step is ordered by merge cost, cheapest first, and nothing edits a Keymind workflow file.

| Phase | What changes | Where | Cost at next Keymind merge |
|-------|--------------|-------|----------------------------|
| A | New `quake-ci.yml` plus one new test; runs alongside Keymind's `test`, not yet required | new files only | none |
| B | Cut over: require `quake-ci`, drop `test` from required, disable two inherited workflows | repository settings only | none |
| C | Keymind-merge runbook: re-enable the full suite for the merge window; revert our `if: false` edit | one existing file, reverted to Keymind's text | none (removes a conflict) |
| D | Workflow inventory document | new file | none |
| E | Version scheme 2.x, reported next to the Keymind base version | our variant file, release tooling, flasher | low |
| F | Consolidate the 7 code seams into marked blocks; optionally upstream | Keymind code files | reduces future conflicts; some risk now |

Phases A to D are the answer to the three costs in the spec (slow gate, wrong coverage, inherited automation). E and F are separable and can wait.

## Technical Context

**Language/Version**: GitHub Actions YAML, Python 3.13 (existing release tooling), C++ (the policy fixture is compiled with the host `g++` by `test/test_rak_gps_power.py`), PlatformIO for the two images.

**Primary Dependencies**: PlatformIO (`pio run -e MeshAmerica_Quake_Repeater_RAK3401`, `..._RAK4631`), the existing `scripts/quake_release_manifest.py`, `gh` CLI for settings changes.

**Storage**: N/A. State lives in repository settings (branch protection, workflow enabled state).

**Testing**: existing `test/test_quake_release_manifest.py`, `test/test_rak_gps_power.py` (compiles `test/fixtures/wisblock_shared_power_policy.cpp`), `pio test -e native` suites `test_d7s` and `test_d7s_wire`; one new test for the quake-image rail default (see research R3).

**Target Platform**: GitHub-hosted `ubuntu-latest` runners; firmware targets nRF52840 (RAK3401, RAK4631).

**Project Type**: firmware repository (CI, release process, build metadata); no new runtime service.

**Performance Goals**: required check at or under 15 minutes (measured baseline: our release workflow builds both images in 2 to 6 minutes); full release wait under 45 minutes.

**Constraints**: never edit or delete a Keymind workflow file; each settings change approved by the owner and reversible; the required check must never be skipped; the release flow and flasher catalog pins (tag `quake-vX.Y.Z.W`) keep working; nothing touches the mesh/internet boundary.

**Scale/Scope**: 2 images, 2 protected branches, 15 workflows (3 are ours), 7 code seams.

## Constitution Check

The project constitution (`.specify/memory/constitution.md`) is still the unfilled template, so no project principles exist to gate against. The binding constraints are therefore the ones recorded by the maintainer and carried into the spec: Keymind merges stay easy; Keymind workflow files untouched; every commit on `main` merged back into `next`; no internet gateway for the mesh. All are respected by the design below. **Gate: pass.** Recommendation: fill in the constitution from those four rules so later features are gated on them.

## Project Structure

### Documentation (this feature)

```text
specs/001-keymind-separation/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and evidence
├── data-model.md        # Phase 1: the entities and their states
├── quickstart.md        # Phase 1: how to verify each phase
├── contracts/
│   └── ci-and-settings.md   # required-check names, workflow states, cut-over order
├── checklists/requirements.md
└── tasks.md             # Next step (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
.github/workflows/
├── quake-ci.yml                 # NEW (Phase A): the required check
├── quake-repeater-release.yml   # existing, ours; keeps its path filter, never required
├── quake-docs-pages.yml         # existing, ours
├── run-unit-tests.yml           # Keymind's; Phase C reverts our `if: false` edit; disabled in settings
└── github-pages.yml             # Keymind's; disabled in settings, file untouched
docs/                            # NOT used for the inventory (mkdocs may publish it)
design/ or .github/              # workflow inventory lives beside the workflows (Phase D)
test/
└── test_quake_rail_default.py   # NEW (Phase A): quake image keeps 3V3_S powered under gps-only
variants/meshamerica_quake/platformio.ini   # version scheme (Phase E)
tools/mota/, scripts/quake_release_manifest.py   # checked for the 2.x scheme (Phase E)
src/helpers/sensors/, examples/simple_repeater/  # the 7 seams (Phase F)
```

**Structure Decision**: all new automation is additive (new files), and everything else is a repository setting or a revert to Keymind's text. The only edits to Keymind-owned files are in Phase F, which is optional and last.

## Phase A: our fast check

1. `quake-ci.yml` triggers on `pull_request` to `main` and `next` and on `push` to `next`, with **no workflow-level `paths:` filter**. Cheap steps run unconditionally. Expensive steps use job-level conditions only if needed, and a skipped step must still let the job succeed (the job, not the step, is the check).
2. One job named `quake-ci` runs: the release-manifest test, the policy fixture test (`test_rak_gps_power.py`), the new rail-default test, `pio test -e native` filtered to the D7S suites, and a build matrix of both images.
3. Keep the build in a matrix job but expose **one** aggregate check (`quake-ci`) so branch protection names a single stable context.
4. The new `test_quake_rail_default.py` compiles the policy fixture with `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL` defined and with it undefined, and asserts the rail stays enabled under `gps-only` for the quake case and would be cut for the stock case. This is the test that would have caught 1.18.0.1.
5. Prove it: revert the sensor-rail hold on a scratch branch and confirm `quake-ci` fails (SC-003).
6. Run `quake-ci` next to Keymind's `test` for several PRs before Phase B. Do not make it required yet.

## Phase B: cut-over (repository settings, owner approves each step)

The order is mandatory: **add, observe, remove, disable**. See [contracts/ci-and-settings.md](contracts/ci-and-settings.md).

1. Add `quake-ci` to required checks on `next` and `main` (alongside `test`).
2. Confirm `quake-ci` has reported on at least three PRs, including a docs-only one.
3. Remove `test` from required checks.
4. Only now, `gh workflow disable` `run-unit-tests.yml` and `github-pages.yml`.
5. Before step 4, verify on a throwaway repository or fork that a disabled workflow stays disabled after a push that changes its file (research R2).
6. Rollback at any step is the reverse single command. Record the previous protection JSON before the first change.

## Phase C: Keymind-merge runbook

`run-unit-tests.yml` cannot be dispatched while disabled, and it triggers on `pull_request`. The runbook for a merge window: enable it, open the `merge/keymind-*` PR (it runs), read the result, merge, disable it again. The temporary `if: false` skip we added to the stock-app compatibility test is reverted at the same time (the file returns to Keymind's text); if that test fails for reasons unrelated to us, the maintainer records it in the PR and proceeds, because the full suite is advisory on Keymind merges and `quake-ci` stays the gate.

## Phase D: inventory

A short table of all 15 workflows: trigger, enabled state, why. Placed beside the workflows (not under `docs/`, which mkdocs may publish).

## Phase E: version scheme

Evidence so far (research R4): auto-install requires `candidate > running` as an unsigned 32-bit compare of the packed version, so 2.0.0.0 (0x02000000) is accepted over 1.18.0.2 (0x01120002). Open items to verify before any release: the flasher catalog validator's ordering rule; `tools/mota/pio_endf.py`; the release workflow's tag derivation; the `ver` command output carrying the Keymind base release. First candidate: `2.0.0.0`.

## Phase F: code seams

Inventory each of the 7 files' additions (about 200 lines), wrap each in one marked block, rebuild both images, and compare telemetry/alert/power behaviour before and after. Offering generic hooks (sensor-rail hold, extra telemetry source) to Keymind is the maintainer's decision, taken after the blocks exist and not before.

## Risks

| Risk | Mitigation |
|------|------------|
| A required check that stays "pending" blocks all merges | no workflow-level path filter; one aggregate job; observed on a docs-only PR before cut-over |
| Disabling the wrong workflow, or in the wrong order, blocks every PR | contract fixes the order; protection JSON saved first; each step one reversible command |
| A disabled workflow comes back after a Keymind merge | verified on a throwaway repo first; checked again after the first real Keymind merge (SC-006) |
| Fast check misses a Keymind regression that matters to us | full suite runs on every Keymind merge PR; plus a release-time smoke build |
| A 2.x version breaks the flasher or OTA | verified against validator and update path before the first release (FR-015) |
| Seam consolidation changes behaviour | before/after build comparison; phase F is optional and last |

## Complexity Tracking

No constitution violations to justify.
