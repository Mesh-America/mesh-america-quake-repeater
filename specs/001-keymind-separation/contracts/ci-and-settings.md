# Contract: required checks, workflow states, cut-over order

This is the interface between the repository and GitHub's settings. Anything here changes only with the owner's approval.

## Required checks (target state)

| Branch | Required context | Source |
|--------|------------------|--------|
| `next` | `quake-ci` | `.github/workflows/quake-ci.yml`, job `quake-ci` |
| `main` | `quake-ci` | same |

`quake-ci` MUST report on every pull request, including documentation-only and workflow-only ones. It MUST NOT sit behind a workflow-level `paths:` filter.

## Workflow states (target)

| Workflow | State | Why |
|----------|-------|-----|
| `quake-ci.yml` | enabled | the gate |
| `quake-repeater-release.yml` | enabled, not required | release; path-filtered |
| `quake-docs-pages.yml` | enabled | our docs site |
| `run-unit-tests.yml` | disabled; enabled only during a Keymind merge | slow; Keymind's |
| `github-pages.yml` | disabled | publishes Keymind's docs |
| `build-*`, `check-mqtt-preset-parity.yml`, `firmware-builder.yml` | unchanged (inert) | triggers do not match our refs |
| `pr-build-check.yml`, `sync-flasher-content.yml`, `stale-bot.yml` | decide in the task list after reading each | |

## Cut-over order (MUST be followed)

1. Save current protection: `gh api repos/Mesh-America/mesh-america-quake-repeater/branches/next/protection` and the same for `main`, to files.
2. Add `quake-ci` to required contexts, keeping `test`. **Owner approves.**
3. Observe: `quake-ci` reports on at least 3 PRs, one of them docs-only.
4. Remove `test` from required contexts. **Owner approves.**
5. `gh workflow disable run-unit-tests.yml`, then `gh workflow disable github-pages.yml`. **Owner approves.**
6. Rollback: re-enable the workflows, then restore the saved protection.

Never do 5 before 4, and never do 4 before 3.

## Keymind merge window

1. `gh workflow enable run-unit-tests.yml`
2. Open the `merge/keymind-*` PR into `next`; the suite runs on it.
3. Read the result; record unrelated failures in the PR text.
4. Merge; `gh workflow disable run-unit-tests.yml`.
5. Check the workflow inventory still matches the settings.
