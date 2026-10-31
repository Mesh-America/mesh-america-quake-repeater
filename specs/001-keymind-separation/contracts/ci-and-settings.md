# Contract: required checks, workflow states, cut-over order

This is the interface between the repository and GitHub's settings. Anything here changes only with the owner's approval.

## Current state (read from GitHub, 2026-10-30)

| Setting | `next` | `main` |
|---------|--------|--------|
| Required context | `test` (app id 15368) | `test` (app id 15368) |
| `strict` (branch must be up to date) | off | off |
| `enforce_admins` | off | off |
| Force-push | allowed | blocked |
| Pull request required | yes, 0 approvals | yes, 0 approvals |

Repository merge methods: merge commits, squash and rebase are all allowed. No rulesets, no merge queue, no tag protection.

Consequence today: a required check binds non-administrators only, and a direct push by the owner (as used for merge-back) is allowed.

## Owner decisions

| Decision | Answer |
|----------|--------|
| Administrators cannot merge around a failed `quake-ci` (`enforce_admins` on) | **on** (owner, 2026-10-30), switched on as the last cut-over step |
| Force-push on `next` | **blocked** (owner, 2026-10-30) |
| Branch must be up to date (`strict`) | **on** (owner, 2026-10-30) |
| First new-scheme version | **2.0.0.0** (owner, 2026-10-30) |
| Repository merge methods | **merge commits only** (owner, 2026-10-30), so a release PR can never be squashed or rebased |
| Tag rule restricting who may create `quake-v*` tags | **none** (owner, 2026-10-30: agents acting for the owner must be able to tag, and the release workflow creates its own tag). Protection comes from the workflow instead: the release depends on `quake-ci` and the tagged commit must be reachable from `main` |

## Required checks (target state)

| Branch | Required context | Source |
|--------|------------------|--------|
| `next` | `quake-ci`, app id 15368 | job id `quake-ci`, no `name:`, in `.github/workflows/quake-ci.yml` |
| `main` | `quake-ci`, app id 15368 | the same, but only after a release has put the workflow file on `main` (a PR cut from a `main` without the file never reports it) |

`quake-ci` MUST be a separate, non-matrix job with `needs: [tests, build, release-metadata]`, a job condition of exactly `${{ always() }}` and no other, and one step that fails unless every `needs.*.result` is `success`. It MUST NOT use a workflow-level `paths:` filter, a `name:`, or `concurrency: cancel-in-progress`. Matrix legs get decorated names such as `build (MeshAmerica_Quake_Repeater_RAK4631)`; only the aggregate is ever required. The context is the job's `name:` or, without one, its id, so no second workflow may define a job with the same name.

## Workflow states (from `gh workflow list --all`)

| Workflow | State now | Target |
|----------|-----------|--------|
| `quake-ci.yml` | does not exist | enabled, required |
| `quake-repeater-release.yml` | active | enabled, not required; release job depends on `quake-ci` |
| `quake-docs-pages.yml` | active | enabled |
| `run-unit-tests.yml` | active | disabled; enabled only during a Keymind merge window |
| `firmware-builder.yml` | active (`workflow_call` only) | unchanged |
| Code scanning, Dependency graph (default setup) | active | unchanged |
| `github-pages`, `pr-build-check`, `sync-flasher-content`, `stale-bot`, `build-companion`, `build-observer*`, `build-repeater`, `build-room-server`, `check-mqtt-preset-parity` | `disabled_manually` since 2026-10-03 | unchanged |

## How settings are changed (verified read-only on 2026-10-30)

- **Required checks and `strict`**: `PATCH repos/{r}/branches/{b}/protection/required_status_checks` with `strict` and `checks:[{context,app_id}]` together every time (the docs do not promise that omitted fields are kept). The PATCH replaces the list. It accepts a context that has never reported without error, so the observation step is the only safety net.
- **`enforce_admins`**: `POST` / `DELETE repos/{r}/branches/{b}/protection/enforce_admins`.
- **Force-push**: no narrow REST endpoint exists (it is settable only through the full PUT body). Use GraphQL `updateBranchProtectionRule`. Verified by query and introspection: the rule fields `allowsForcePushes`, `requiresStrictStatusChecks`, `isAdminEnforced`, `requiredStatusChecks{context, app{databaseId}}` exist, and the mutation input has `allowsForcePushes`, `isAdminEnforced`, `requiresStrictStatusChecks`, `requiredStatusChecks`. Rule IDs: `next` = `BPR_kwDOU5wo6s4FBIyZ`, `main` = `BPR_kwDOU5wo6s4FBUvs`. Not yet verified: that omitted fields in the mutation are left unchanged (test on a throwaway repository first), and a before/after diff of the query result is the check after every change.
- Never replay the GET output of the REST protection as a PUT body: the shapes differ and a PUT replaces everything, including the "pull request required" rule.
- **Merge methods**: repository setting, merge commits only (proposed).

## Cut-over order (MUST be followed)

1. Land `quake-ci.yml` on `next`. Push to or reopen any PR that predates it.
2. Observe: `quake-ci` reports on at least 3 PRs, including one docs-only and one workflow-only. Also check what a YAML syntax error does (no check at all, so the check hangs).
3. Save the current protection: the GraphQL query result for both rules, and the REST `required_status_checks`.
4. On `next`: add `quake-ci` (app id 15368), keeping `test`. **Owner approves.** `main` waits until the first release carries the workflow file.
5. Remove `test`. **Owner approves.**
6. `gh workflow disable run-unit-tests.yml`. **Owner approves.**
7. Write the release ritual (below) into the contributor notes.
8. Set the repository merge methods to merge commits only. **Owner approves.** (No tag rule: the release workflow's own token creates the tag, and agents work under the owner's identity.)
9. Last: `strict` on, force-push blocked on `next`, `enforce_admins` on, both branches. **Owner approves.**
10. Rollback: `isAdminEnforced:false`, then `allowsForcePushes` and `requiresStrictStatusChecks` back to the saved values, `gh workflow enable run-unit-tests.yml`, then PATCH the saved checks. Restoring `test` as required is valid only before the Keymind-merge window has reverted our skip (afterwards the stock-app step is red by design).

Never do 6 before 5, 5 before 4, 4 before 2, or 9 before `quake-ci` has gone green on every kind of PR.

## Release ritual once step 9 is done

1. Feature PRs into `next` with merge commits.
2. Release PR from `next` into `main`, merge commit only.
3. After it lands, `main` is one commit ahead of `next`. **Merge-back is a pull request**: branch `merge/main-into-next-<n>` from `next`, merge `main` into it, open a PR into `next`, wait for `quake-ci`, merge. Never a PR with head `main`. Direct pushes to `next` are rejected.
4. The next release PR cannot merge until step 3 has landed (the up-to-date rule).
5. Every other open PR into `next` must be refreshed after each merge.

## Break-glass

With `enforce_admins` on there is no merge-time bypass. If `quake-ci` cannot run for a reason outside the repository (runner or PlatformIO outage): the owner removes `quake-ci` from the required list (PATCH, `strict` kept), merges, writes the reason on the PR, and restores the requirement immediately. That is a settings change, visible in the audit log. If `quake-ci.yml` itself is broken, a fix PR runs its own corrected copy from its merge ref (a conflicted PR runs nothing, and a syntax error produces no check, so the fix PR must be conflict-free and up to date). Each use is noted in the PR.

Known limit: a pull request runs its own copy of `quake-ci.yml`, so it can change its own check. The owner reviews any diff touching `.github/**` and `scripts/` for that reason.

## Keymind merge window

1. `gh workflow enable run-unit-tests.yml`.
2. Branch `merge/keymind-<release>` from `next`; resolve conflicts so the PR is mergeable (a conflicted PR starts no `pull_request` workflows).
3. **Push or reopen** the PR. Dispatching with `gh workflow run run-unit-tests.yml --ref merge/keymind-<release>` is a fallback only, and it tests the branch tip, not the merge ref against `next`.
4. Record the verdict on the PR: pass, or the same failure on the pristine Keymind tag. Expect the stock-app compatibility step to be red after our `if: false` skip is reverted. `quake-ci` fails the PR until a completed run exists for its head commit.
5. Merge; `gh workflow disable run-unit-tests.yml`; run `scripts/check_workflow_inventory.py` (window mode off).
6. Merge-back as in the ritual; record time and conflicts.
