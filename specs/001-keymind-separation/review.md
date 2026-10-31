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
| 3 | Gate is advisory for the owner: `enforce_admins:false`, `strict:false`, no reviews, force-push on `next` | **Fixed by owner decision (2026-10-30)**: `enforce_admins` on, `strict` on, force-push on `next` blocked (contract, FR-019) |
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
| 20 | Phase E said it edits Keymind-owned code (`ver` hook) and relies on Keymind's version tooling; `mesh-america/*` and `scripts/generate_mesh_america_release.py` never read | **Fixed**: `ver` is built in our own `MyMeshQuake.cpp:280`, so no new seam (checked). The Keymind `mesh-america/*` tooling was dropped as out of scope: the owner confirmed it only feeds Keymind into the Device Configurator app |
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


---

# Round 2: re-review of the revisions

Two fresh reviewers, again given only the files and the repository. Lens 1: whether the settings contract can be executed exactly as written against GitHub's real API and behaviour (read-only calls). Lens 2: spec/plan traceability and feasibility of the code-level claims. Dispositions as above.

## Blockers

| # | Finding | Disposition |
|---|---------|-------------|
| R2-1 | Merge-back (`chore: merge main back into next`) is a direct push of a merge commit with no PR (six or more times); with `enforce_admins` on and a PR required it is rejected, and a fresh merge commit never has a green check | **Fixed**: merge-back becomes a PR with a documented release ritual (FR-021, contract, plan Phase B) |
| R2-2 | No executable command for blocking force-push on `next`: no narrow REST endpoint; a hand-built PUT can drop settings including "pull request required"; rollback never restored `strict` or force-push | **Fixed**: GraphQL `updateBranchProtectionRule`; field names and rule IDs verified read-only (contract); full rollback list; "omitted fields unchanged" still to be tested on a throwaway repo |
| R2-3 | Contract contradicted itself on `if: always()` (a "job-level `if:`" banned and required) | **Fixed**: "a job condition of exactly `${{ always() }}` and no other" |
| R2-4 | The rail test cannot go red as designed: the lifecycle harness compares against `compile_held` computed from the same macro, and the real `build_flags` cannot be handed to the host compiler | **Fixed**: whitelist of rail-relevant defines, expected masks 16 / 1 fixed in the test, existing fixture's `static_assert` (plan A4, R3) |

## High

| # | Finding | Disposition |
|---|---------|-------------|
| R2-5 | Tag pushes bypass every gate (release `needs` only its own build; no rulesets); release on a push to `main` runs in parallel with the checks; FR-019 was false as written | **Fixed**: release depends on `quake-ci`, tagged commit must be reachable from `main` (FR-018, FR-019, plan A8). A tag-creation rule was proposed, then dropped by the owner's decision (agents must be able to tag; the release workflow tags with its own token) |
| R2-6 | Version-ordering check can pass on empty data (shallow checkout, no tags); "changed" undefined; merge-back PRs carry the same version; string vs numeric compare | **Fixed**: full history and tags, merge-base comparison, numeric, merge-back exempt, compare built manifests not `platformio.ini` (plan A5) |
| R2-7 | `strict` adds a hidden dependency on every release (next is always one commit behind) and every sibling PR must be refreshed; squash and rebase are allowed | **Fixed**: ritual, merge-commit-only proposal, SC-002 counts the merge-back PR (<60 min) |
| R2-8 | Hotfix PRs cut from a `main` without the workflow file never report | **Fixed**: require on `main` only after a release carries the file (FR-022) |
| R2-9 | Runbook dispatch tests the branch tip, not the merge ref | **Fixed**: push or reopen is primary; dispatch a fallback |
| R2-10 | FR-005 only procedural; nothing fails if the Keymind window is skipped | **Fixed**: `quake-ci` fails a `merge/keymind-*` PR until a completed run exists for its head SHA |
| R2-11 | `ver` consumers misdescribed (no advert/telemetry code reads the version; owner-info would disagree with `ver`; official-app behaviour on major 2 not tasked) | **Fixed**: real consumer list, owner-info decision, open question tasked (plan E) |

## Medium / Low

| # | Finding | Disposition |
|---|---------|-------------|
| R2-12 | Rollback to `test` invalid after Phase C reverts the skip; numbering differed between plan and contract | **Fixed** (contract step 10) |
| R2-13 | FR-017 overclaim: a PR can edit `quake-ci.yml` itself | **Accepted**, stated as a known limit; owner reviews `.github/**` diffs |
| R2-14 | Conflicted PR and syntax-error behaviour | **Fixed**: edge cases, cut-over step 2 |
| R2-15 | Three different fault lists (SC-003, plan, quickstart); smoke build and ordering had no red case; RAK3401 "sensor-rail hold" is not a thing (its hold is radio power) | **Fixed**: one list F1 to F8 and masks 16 / 1 |
| R2-16 | Suite counting contradictory (`not zero` vs `four`); unfiltered `native` is about 114 suites; four suites still compile ~40 Keymind sources | **Fixed**: exactly four, from a report; `native_quake` decided after measuring |
| R2-17 | Smoke build under-specified (Keymind's uses `build.sh`, two profiles, 13 min; `RAK_4631_repeater` differs on OTA) | **Fixed**: plain `pio run` of a named sibling, chosen in tasks |
| R2-18 | Keymind regression tests beyond the policy test drop out of the gate | **Accepted, listed**: candidates named, chosen in tasks |
| R2-19 | `KEYMIND_BASE_VERSION` has no source of truth; `FIRMWARE_VERSION` is hand-copied per environment | **Fixed**: shared `[quake_version]` section, `git tag --merged HEAD` |
| R2-20 | Inventory drift check misses on-disk files, needs a window mode and `actions: read`; not scheduled from `quake-ci` | **Fixed** (plan D) |
| R2-21 | Checklist boxes not honest; stale statements (owner decision "open", one inherited workflow active, file counts 86 + 28, churn figures not reproducible) | **Fixed**: checklist rewritten; counts corrected; churn reference required |
| R2-22 | FR numbering out of order; FR-012 and US3 title overclaim | **Fixed**: reordered, FR-012 reworded (assumes Keymind stays on major 1) |

## Verified by the second round (do not re-litigate)

`enforce_admins` POST/DELETE exist; `app_id` 15368 is the Actions pin; no rulesets or merge queue exist; conflicted PRs run no `pull_request` workflows; a separate non-matrix aggregate job gives a context named exactly `quake-ci`; the push-to-`main` ordering race is avoided by the pull-request-only rule; `MyMeshQuake.cpp:280` builds `ver`; 114 / 11 / 206 and the hunk counts reproduce.

## Still unverified

PlatformIO config resolution in CI and the unmatched-filter exit status (neither reviewer had `pio`); GraphQL "omitted fields unchanged"; whether `gh workflow list --all` shows a workflow file that exists only on a branch; whether the legacy `_cli.handleCommand` call at `MyMesh.cpp:12786` is compiled out of the quake image; `gh` cold-cache timing of `quake-ci`; whether official apps change behaviour on repeater major version 2.
