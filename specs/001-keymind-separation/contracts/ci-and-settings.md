# Contract: required checks, workflow states, cut-over order

This is the interface between the repository and GitHub's settings. Anything here changes only with the owner's approval.

## Current state (read from GitHub, 2026-10-30)

- `next` and `main`: required context `test` (app id 15368, GitHub Actions); `strict:false`; `enforce_admins:false`; zero required reviews; no merge queue, no rulesets. `next` also allows force pushes.
- Consequence: a required check binds non-administrators only. The owner can merge around it.

## Required checks (target state)

| Branch | Required context | Source |
|--------|------------------|--------|
| `next`, `main` | `quake-ci`, app id 15368 | job `quake-ci` in `.github/workflows/quake-ci.yml` |

`quake-ci` MUST be a separate, non-matrix job with `needs: [tests, build]`, `if: ${{ always() }}`, and a step that fails unless every `needs.*.result` is `success`. It MUST NOT use a workflow-level `paths:` filter, a job-level `if:` on itself, or `concurrency: cancel-in-progress`. Matrix legs get decorated names such as `build (MeshAmerica_Quake_Repeater_RAK4631)`; only the aggregate is ever required.

## Owner decisions (record the answer here before Phase B)

| Decision | Options | Answer |
|----------|---------|--------|
| Bind administrators (`enforce_admins`) | off (today) / on | _open_ |
| Force-push on `next` | allowed (today) / blocked | _open_ |
| Require branch up to date (`strict`) | off (today) / on | _open_ |
| First new-scheme version | 2.0.0.0 / other | _open_ |

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
7. Rollback: `gh workflow enable run-unit-tests.yml`, then PATCH the saved `checks` array. Never replay the full protection JSON (the PUT body differs from the GET output and would drop settings).

Never do 6 before 5, 5 before 4, or 4 before 2.

## Break-glass

If `quake-ci` cannot run (runner outage, renamed job, broken workflow file): the owner removes it from the required list (PATCH as above) or merges as administrator, writes the reason on the PR, and restores the requirement afterwards. Each use is noted in the PR.

## Keymind merge window

1. `gh workflow enable run-unit-tests.yml`.
2. Branch `merge/keymind-<release>`; resolve conflicts so the PR is mergeable (a conflicted PR starts no `pull_request` workflows).
3. Push or reopen the PR, or `gh workflow run run-unit-tests.yml --ref merge/keymind-<release>`.
4. Record the verdict on the PR: pass, or failure shown to be the same on the pristine Keymind tag. Expect the stock-app compatibility step to be red after our `if: false` skip is reverted.
5. Merge; `gh workflow disable run-unit-tests.yml`; run `scripts/check_workflow_inventory.py`.
6. Merge `main` back into `next` if needed; record time and conflicts.
