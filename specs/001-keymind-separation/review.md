# Hostile review log

Three independent reviewers, each given only the files and the repository (no history, no conclusions), each with a different lens, on 2026-10-30. Read-only; the merge-cost reviewer trial-merged in a throwaway worktree (removed).

Dispositions: **Fixed** = plan or spec changed; **Accepted** = valid, recorded as a risk or owner decision; **Open** = needs an answer before tasks run.

## Blockers

| # | Finding | Lens | Disposition |
|---|---------|------|-------------|
| 1 | Aggregate `quake-ci` could be skipped when the build fails, and a skipped required check passes; a matrix job would also never produce a bare `quake-ci` context; plan A.2 and A.3 contradicted each other | mechanics, requirements | **Fixed**: separate non-matrix `quake-ci` job, `needs: [tests, build]`, `if: always()`, fails unless all results are `success` (FR-017, plan A.2, contract) |
| 2 | The rail test as designed passed its own `-D` flag, so deleting the real flag from `platformio.ini` left it green; SC-003 was unreachable. The `gps-only` behaviour is in a lifecycle harness, not the policy fixture | requirements, merge-cost | **Fixed**: test parses the real environment `build_flags` and feeds them to the harness (plan A.4, FR-002); proven red on a scratch branch (quickstart A.3) |

## High

| # | Finding | Disposition |
|---|---------|-------------|
| 3 | Gate is advisory for the owner: `enforce_admins:false`, `strict:false`, no reviews, force-push on `next` | **Accepted**, made explicit; owner decisions table in the contract (FR-019) |
| 4 | Workflow inventory wrong: most inherited workflows were disabled on 2026-10-03; only `run-unit-tests.yml` is active; `github-pages` is not publishing to our site; CodeQL and Dependency graph unmentioned | **Fixed**: spec, plan, contract and research rewritten from `gh workflow list --all` |
| 5 | Phase A listed 2 of 4 earthquake suites (`test_seismic_alert`, `test_clock_floor` missing); an unmatched `pio test` filter may pass vacuously | **Fixed**: all four, with a suite-count check (FR-002) |
| 6 | "Correct for each image" only defined for RAK4631; RAK3401 has no stated expectation | **Fixed**: both asserted (FR-002, plan A.4) |
| 7 | No hotfix path if `quake-ci` is broken; tag-only releases skip the gate; `quake-ci` not run on pushes to `main` | **Fixed**: break-glass procedure, tag releases gated, push to `main` added (FR-018, FR-019) |
| 8 | Keymind-merge safety net is advisory; "ordinary PR does not run it" false during a window; no objective test for "unrelated" failure; enabling a workflow runs nothing on an open PR; conflicted PRs start no workflows | **Fixed**: runbook with dispatch, verdict recorded against the pristine Keymind tag, window acknowledged (US2, Phase C) |
| 9 | Phase F "one marked block per file" is unachievable (`MyMesh.cpp` 8 hunks, `MyMesh.h` 4, policy header 3; four of our lines edit existing Keymind lines) and moving code in the most-churned file may make conflicts worse | **Fixed**: requirement reframed as seam inventory plus trial-merge conflict list; F is conditional (FR-010, US5, Phase F) |
| 10 | SC-007 / US3 AC3 vacuous: auto-install is off by default and needs signed packages; Quake updates by USB/Bluetooth DFU or manual `ota install`, which have no version gate | **Fixed**: acceptance moved to the paths users take (US3 AC3, SC-007) |
| 11 | FR-014 had no design; the version string feeds adverts, MQTT, SNMP, owner info | **Fixed**: base release goes only in `ver`, bare version unchanged, CI staleness check, flasher regex kept (FR-014, Phase E) |
| 12 | FR-012 overreached: no mechanism collides today (target ID, tag prefix and repo differ); the harm is human confusion | **Fixed**: wording changed; 2.x remains an owner decision |

## Medium

| # | Finding | Disposition |
|---|---------|-------------|
| 13 | Contract added the requirement before observing it, contradicting the plan | **Fixed**: land, observe, add, remove, disable |
| 14 | "Rollback = restore saved protection JSON" cannot work (PUT body differs; full replace) and the existing check has `app_id` 15368 | **Fixed**: narrow `required_status_checks` PATCH, app id pinned, roll back the `checks` array |
| 15 | Release metadata check lived only in the post-merge release job; version mismatch between the two images passes `quake-ci` today | **Fixed**: version-consistency and monotonicity check in `quake-ci` (FR-002) |
| 16 | Duplicate builds between `quake-ci` and the release workflow; 15-minute target rests on a warm-cache baseline | **Accepted**: decide reuse vs duplicate in tasks after measuring cold-cache time |
| 17 | Stock builds not covered: our hooks sit in shared headers (`SensorManager.h`) | **Fixed**: stock RAK4631 smoke build in `quake-ci` (FR-002) |
| 18 | Phase C revert claim true only against the old base; the revert must not land while `test` is still required; the stock-app test then fails by design | **Fixed**: revert inside the first merge window; blob identities stated; red step expected |
| 19 | "Merge cost none" is wrong as a general claim: merge cost is episodic (the 1.18.0.1 merge had 4 conflicting files and a rewritten base); today's trial merge of the newest upstream tip had **0** conflicts | **Accepted**: stated in risks; baseline recorded as SC-005 |
| 20 | Phase E said it edits Keymind-owned code (`ver` hook) and relies on Keymind's version tooling; `mesh-america/*` and `scripts/generate_mesh_america_release.py` never read | **Partly fixed**: `ver` is built in our own `MyMeshQuake.cpp:280`, so no new seam (checked); **Open**: read the Keymind release tooling before tasks (Phase E item 1) |
| 21 | Unmeasurable criteria (FR-003 "typical", SC-002 "waiting", SC-004 sample of 10, SC-005, SC-008 baseline) | **Fixed**: percentile/cold cache; synthetic PRs; conflict-site list; time recording from the next merge |
| 22 | Release workflow has no ordering guard (`--latest` always) | **Fixed** via the monotonicity check |
| 23 | Bot-created PRs using the automatic token start no workflows | **Fixed**: FR-020 |
| 24 | Apps flasher `previousReleases` edit and fixture for FR-015 unplanned | **Fixed**: Phase E item 4 |

## Low / corrected facts

- Disabled-state persistence (R2): partly measured (a later merge changed `build-repeater-firmwares.yml` and it stayed disabled); real risk is added or renamed workflow files. **Fixed** (R2, Phase D drift check).
- "114 ours-only files" overstates code: about 40 are source, tests and docs; the rest is site output. **Fixed** in the spec background.
- Added lines are 206 (matches "about 200"); the 11 files and 114 count were reproduced.
- Workflow count: 15 files, 2 ours today (the plan said 3).
- Phase C / data-model "byte-identical to Keymind's" now names the reference.

## Not verified by anyone

- Cold-cache run time of `quake-ci`; `pio test` exit status with an unmatched filter.
- Whether official apps gate on the repeater version string (1.x to 2.x).
- Whether a Keymind 2.x is planned.
- Fork and bot PR behaviour in this repo (no examples).
- The newest upstream tip compiles after the trial merge (only textual conflicts were checked).

## Verified true (do not re-litigate)

1.18.0.2 = 0x01120002; 2.0.0.0 = 0x02000000; build tooling, tag derivation, manifest and flasher accept 2.x; the 11-file / 114-file counts; `test` is the only required context; `run-unit-tests.yml` triggers; the only divergence in that file is our 7-line skip; neither new file name clashes with upstream; the cut-over order never deadlocks `test` against the disable.
