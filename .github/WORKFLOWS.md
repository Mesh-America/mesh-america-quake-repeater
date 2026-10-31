# Workflow inventory

What runs in this repository and why. The table is read by `scripts/check_workflow_inventory.py`,
which compares it with the workflows GitHub reports and the files on disk, so keep each row in the
form `| \`path\` | expected state | triggers | why |`. Plan: `specs/001-keymind-separation/`.

State is the workflow's state in repository settings (`gh workflow list --all`). Keymind's workflow
files are never edited here; the ones that do not apply to us are switched off in settings.

| Workflow | Expected state | Triggers | Why |
|----------|----------------|----------|-----|
| `.github/workflows/quake-ci.yml` | active | pull request to main/next, push to next, called by the release workflow | Ours. The required check `quake-ci`: tests, both images, stock smoke builds, release metadata. |
| `.github/workflows/quake-repeater-release.yml` | active | PR (path filtered), push to main/next, `quake-v*` tags | Ours. Builds the two images and publishes the release; the release job depends on `quake-ci`. Never a required check (path filter). |
| `.github/workflows/quake-docs-pages.yml` | active | push to main (path filtered) | Ours. Deploys quakerepeater.meshamerica.com. |
| `.github/workflows/run-unit-tests.yml` | active | push to main/master/keymindCascade, every PR, manual | Keymind's full suite (1 to 1.6 h). Active until cut-over step 6 (task qr-fgy.16), then disabled except during a Keymind merge window. |
| `.github/workflows/firmware-builder.yml` | active | `workflow_call` only | Keymind's reusable build helper; runs only when another workflow calls it. |
| `dynamic/github-code-scanning/codeql` | active | default setup | GitHub code scanning (not file-backed). |
| `dynamic/dependabot/update-graph` | active | default setup | Dependency graph (not file-backed). |
| `.github/workflows/build-companion-firmwares.yml` | disabled_manually | tags `companion-*` | Keymind release build; not ours. |
| `.github/workflows/build-observer-firmwares-beta.yml` | disabled_manually | branch `observer-firmware-dev` | Keymind release build; not ours. |
| `.github/workflows/build-observer-firmwares.yml` | disabled_manually | branch `observer-firmware` | Keymind release build; not ours. |
| `.github/workflows/build-observer-plus-firmwares.yml` | disabled_manually | manual | Keymind release build; not ours. |
| `.github/workflows/build-repeater-firmwares.yml` | disabled_manually | tags `repeater-*` | Keymind release build; not ours. |
| `.github/workflows/build-room-server-firmwares.yml` | disabled_manually | tags `room-server-*` | Keymind release build; not ours. |
| `.github/workflows/check-mqtt-preset-parity.yml` | disabled_manually | observer branches | Keymind check; not ours. |
| `.github/workflows/github-pages.yml` | disabled_manually | push to main/keymindCascade | Publishes Keymind's mkdocs site to `gh-pages`; our site is deployed by `quake-docs-pages.yml`. |
| `.github/workflows/pr-build-check.yml` | disabled_manually | PR to main/dev (path filtered) | Keymind PR build; replaced by `quake-ci`. |
| `.github/workflows/stale-bot.yml` | disabled_manually | schedule | Keymind issue housekeeping. |
| `.github/workflows/sync-flasher-content.yml` | disabled_manually | Keymind flasher content sync | Keymind flasher; not ours. |

## Keymind merge window

`run-unit-tests.yml` is enabled for the duration of a `merge/keymind-*` pull request and disabled again
afterwards. During the window run the check as `python3 scripts/check_workflow_inventory.py --window
run-unit-tests.yml` and, afterwards, without `--window`.

## A new workflow file arrives from Keymind

It arrives enabled. The drift check reports it (it is on disk but not in this table). Decide, add a row,
and disable it in settings (`gh workflow disable <file>`) unless it is ours.
