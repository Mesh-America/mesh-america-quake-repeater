# quake-ci fault drill: results (2026-10-31)

Task qr-fgy.12. Each case is a scratch branch cut from the PR 45 head (`feat/quake-ci`, commit 9cd01c7fa)
with one deliberate change, pushed so that only `quake-ci` runs (the scratch copy of the workflow adds a
`push` trigger for `scratch/**`; no pull request, so Keymind's long suite did not start). All scratch
branches were deleted afterwards. Expected versus observed:

| Case | Change | Expected | Observed `quake-ci` | What turned red |
|------|--------|----------|---------------------|-----------------|
| g0 control | none | green | **success** | nothing |
| g1 | three of the four earthquake suites selected | red | **failure** | `tests` (suite count check) |
| g2 | invalid YAML in `quake-ci.yml` | red / no check | **no jobs at all** (run failed) | the run fails at parse time; no `quake-ci` context is ever created |
| g3 | documentation-only change | green | **success** | nothing |
| g4 | workflow-only change (another workflow) | green | **success** | nothing |
| F1 | RAK3401 image fails to build | red | **failure** | `build (RAK3401)`; `release-metadata` skipped; `quake-ci` still failed |
| F2 | RAK4631 sensor-rail hold removed (the 1.18.0.1 defect) | red | **failure** | `tests` (rail test); **both image builds stayed green** |
| F3 | RAK3401 radio-power hold removed | red | **failure** | `tests` (rail test); builds stayed green |
| F4 | an earthquake alert test fails | red | **failure** | `tests` |
| F5 | the two images carry different versions | red | **failure** | `release-metadata` |
| F6 | both versions set below the newest release tag | red | **failure** | `release-metadata` |
| F7 | a stock smoke build fails | red | **failure** | `stock-smoke`; `quake-ci` failed |
| r1 | release path (see below) | release refuses a commit not on `main` | **refused** | the `release` job's guard step |

12 of 12 cases, plus r1, behaved as predicted.

## What this proves

- F2 and F3 are the point: with the sensor-rail hold removed, both images **still build and package**, so
  only the new rail test catches it. That is exactly how 1.18.0.1 got out.
- A skipped dependency (F1's `release-metadata`) still fails the aggregate: the check fails closed.
- Documentation-only and workflow-only changes get a green `quake-ci`, never pending.
- A syntax error in `quake-ci.yml` creates **no check at all**. On a pull request into a branch that
  requires `quake-ci`, GitHub would show the check as expected and never reporting. This is why the cut-over
  observes the check first and why the break-glass note says a fix pull request must be conflict-free and
  syntactically valid.

## r1: the release path

On a scratch branch with the publish step disabled (so nothing could be released), the release workflow's
`checks` job called `quake-ci.yml` as a reusable workflow: every job ran and `checks / quake-ci` succeeded
(the `actions: read` and `contents: read` permissions are accepted). The `release` job then failed at "The
release commit must be on main" (`... is not part of main's history, so it cannot be released.`), and the
later steps (download, tag, create release) were skipped. No release was created (the latest release is
still 1.18.0.2).

## Not exercised

- The strict "must be greater than the newest tag" rule on a pull request. It needs a pull request event and
  is covered by unit tests (14 cases in `test/test_quake_version_check.py`); it will be exercised by the
  first real version-bump pull request.
- The Keymind-merge guard (`merge/keymind-*` head ref): needs such a pull request; first Keymind merge window.
- Cancelling a run partway (`quake-ci` reports cancelled, not success; expected from GitHub semantics, not
  tested).
- The positive path of the release guard (a commit that *is* on `main`): first real release after merge.
- A tag push.

## Settings-behaviour drill (task qr-fgy.3, 2026-10-31)

Run in a throwaway public repository (`tjdownes/quake-settings-drill`; never in this repository). Observed with
`gh` against live GitHub:

| Question | Result |
|----------|--------|
| Does a manually disabled workflow stay disabled when its file's contents change? | **Yes.** State stayed `disabled_manually`, and the push started no run of it. |
| Does it stay disabled when the file is renamed? | **No.** The renamed file is a new workflow, `active`. |
| Is a newly added workflow file enabled? | **Yes**, `active` immediately. |
| Does `gh workflow list --all` show a workflow file that exists only on a non-default branch? | **Yes**, once the branch is pushed (it showed `active`). |
| Does GraphQL `updateBranchProtectionRule` leave omitted fields unchanged? | **Yes.** Setting only `isAdminEnforced`, then only `allowsForcePushes` + `requiresStrictStatusChecks`, left the required checks, review count and the other flags as they were. |
| Does REST `PATCH .../required_status_checks` with only `checks` change `strict`? | **No**, `strict` kept its previous value. (The contract still sends both together, which is harmless.) |

Consequences:

- A Keymind merge that **renames** `run-unit-tests.yml` or `github-pages.yml`, or adds a workflow, brings an
  **enabled** workflow. The inventory check (`scripts/check_workflow_inventory.py`) is what catches this; it
  must stay a part of every Keymind merge window.
- A workflow added on any pushed branch is registered and listed, so the inventory check should treat
  unexpected entries from `--all` as errors regardless of branch.
- The tag-ruleset case was not run: that rule was dropped by owner decision.

The throwaway repository could not be deleted from here (the token has no `delete_repo` scope); delete it from
the GitHub UI.
