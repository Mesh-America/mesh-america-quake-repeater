# Contract: required checks, workflow states, cut-over order

This is the interface between the repository and GitHub's settings. Anything here changes only with the owner's approval.

## Current state (read from GitHub, 2026-10-30)

- `next` and `main`: required context `test` (app id 15368, GitHub Actions); `strict:false`; `enforce_admins:false`; zero required reviews; no merge queue, no rulesets. `next` also allows force pushes.
- Consequence today: a required check binds non-administrators only. The owner can merge around it. **Target (owner decision, 2026-10-30): administrators must not be able to work around a failed `quake-ci`.**

## Required checks (target state)

| Branch | Required context | Source |
|--------|------------------|--------|
| `next`, `main` | `quake-ci`, app id 15368 | job `quake-ci` in `.github/workflows/quake-ci.yml` |

`quake-ci` MUST be a separate, non-matrix job with `needs: [tests, build]`, `if: ${{ always() }}`, and a step that fails unless every `needs.*.result` is `success`. It MUST NOT use a workflow-level `paths:` filter, a job-level `if:` on itself, or `concurrency: cancel-in-progress`. Matrix legs get decorated names such as `build (MeshAmerica_Quake_Repeater_RAK4631)`; only the aggregate is ever required.

## Owner decisions (record the answer here before Phase B)

| Decision | Options | Answer |
|----------|---------|--------|
| Bind administrators (`enforce_admins`) | off (today) / on | **on** (owner, 2026-10-30): admins cannot merge around a failed `quake-ci`; turned on as the last cut-over step |
| Force-push on `next` | allowed (today) / blocked | **blocked** (owner, 2026-10-30) |
| Require branch up to date (`strict`) | off (today) / on | **on** (owner, 2026-10-30) |
| First new-scheme version | 2.0.0.0 / other | **2.0.0.0** (owner, 2026-10-30) |

## Workflow states (target; from `gh workflow list --all`)

| Workflow | State now | Target |
|----------|-----------|--------|
| `quake-ci.yml` | does not exist | enabled, required |
| `quake-repeater-release.yml` | active | enabled, not required (PR trigger is path-filtered) |
| `quake-docs-pages.yml` | active | enabled |
| `run-unit-tests.yml` | active | disabled; enabled only during a Keymind merge window |
| `firmware-builder.yml` | active (`workflow_call` only) | unchanged |
| Code scanning, Dependency graph (default setup, not file-backed) | active | unchanged |
| `github-pages`, `pr-build-check`, `sync-flasher-content`, `stale-bot`, `build-companion`, `build-observer*`, `build-repeater`, `build-room-server`, `check-mqtt-preset-parity` | `disabled_manually` since 2026-10-03 | unchanged |

## Cut-over order (MUST be followed)

1. Land `quake-ci.yml`. No open PR may predate it; push to or reopen any that do.
2. Observe: `quake-ci` reports on at least 3 PRs, including one docs-only and one workflow-only.
3. Save the current required checks (`gh api repos/Mesh-America/mesh-america-quake-repeater/branches/{next,main}/protection/required_status_checks`). Keep the full protection JSON only as a record.
4. Add `quake-ci` to the required checks, keeping `test`, using `PATCH .../protection/required_status_checks` with `checks:[{context:"quake-ci",app_id:15368},{context:"test",app_id:15368}]`. **Owner approves.**
5. Remove `test` the same way. **Owner approves.**
6. `gh workflow disable run-unit-tests.yml`. **Owner approves.**
7. Turn on `strict`, block force-push on `next`, and turn on `enforce_admins` on both branches (`POST/DELETE .../protection/enforce_admins`, the narrow endpoints). Last, so that a not-yet-proven check never locks the owner out. **Owner approves.**
8. Rollback: `DELETE .../protection/enforce_admins` first, then `gh workflow enable run-unit-tests.yml`, then PATCH the saved `checks` array. Never replay the full protection JSON (the PUT body differs from the GET output and would drop settings).

Never do 6 before 5, 5 before 4, 4 before 2, or 7 before `quake-ci` has gone green on every kind of PR in step 2.

## Break-glass

With `enforce_admins` on there is no merge-time bypass. If `quake-ci` cannot run because of something outside the repository (runner or PlatformIO outage): the owner removes `quake-ci` from the required list (PATCH as above), merges, writes the reason on the PR, and restores the requirement immediately afterwards. That is a settings change, visible in the repository's audit log, not a silent merge override. If `quake-ci.yml` itself is broken, a fix PR runs the fixed workflow file (a `pull_request` run uses the PR's own copy), so most breakages heal without using break-glass. Each use is noted in the PR.

## Keymind merge window

1. `gh workflow enable run-unit-tests.yml`.
2. Branch `merge/keymind-<release>`; resolve conflicts so the PR is mergeable (a conflicted PR starts no `pull_request` workflows).
3. Push or reopen the PR, or `gh workflow run run-unit-tests.yml --ref merge/keymind-<release>`.
4. Record the verdict on the PR: pass, or failure shown to be the same on the pristine Keymind tag. Expect the stock-app compatibility step to be red after our `if: false` skip is reverted.
5. Merge; `gh workflow disable run-unit-tests.yml`; run `scripts/check_workflow_inventory.py`.
6. Merge `main` back into `next` if needed; record time and conflicts.
