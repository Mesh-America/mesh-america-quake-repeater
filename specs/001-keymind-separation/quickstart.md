# Quickstart: verifying each phase

## Phase A — the new check
1. Open a PR that changes only a Quake Repeater file. Expect `quake-ci` green in 15 minutes or less.
2. Open a docs-only PR. Expect `quake-ci` to report (green), never pending.
3. On a scratch branch remove `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL` from the RAK4631 environment. Expect `quake-ci` red, failing the rail-default test (this reproduces the 1.18.0.1 defect).
4. On a scratch branch break the input of `test/test_quake_release_manifest.py`. Expect red.

## Phase B — cut-over
1. Before changing anything, confirm the disabled-stays-disabled behaviour on a throwaway repository.
2. After step 5 of the contract, open a PR: only `quake-ci` and the other enabled workflows run; `gh workflow list` shows the two disabled.

## Phase C — Keymind merge
1. Create `merge/keymind-trial` from `next` and merge the latest Keymind release into it.
2. Enable the suite, open the PR, confirm the full suite runs, then disable it again.
3. Confirm `run-unit-tests.yml` equals Keymind's text (diff against the Keymind ref is empty).

## Phase E — version
1. Build both images with the candidate version; run `scripts/quake_release_manifest.py` and `tools/mota/pio_endf.py`.
2. Flasher: run the apps catalog build with the candidate pinned; confirm 1.18.0.2 appears under earlier versions.
3. On a device running 1.18.0.2 perform the update; confirm no override is needed.

## Phase F — seams
1. Build both images before and after; compare behaviour on hardware (telemetry shows the D7S and RAK1906, alerts fire, `peripherals.mode gps-only` keeps the rail on).
