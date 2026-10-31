# Quickstart: verifying each phase

## Phase A — the new check
1. Open a PR that changes only a Quake Repeater file. Expect `quake-ci` green in 15 minutes or less.
2. Open a docs-only PR. Expect `quake-ci` to report (green), never pending.
3. On a scratch branch remove `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL` from the RAK4631 environment in `variants/meshamerica_quake/platformio.ini`. Expect `quake-ci` red from the rail test (this reproduces the 1.18.0.1 defect).
4. Make the two `FIRMWARE_VERSION` values differ. Expect red.
5. Break one matrix leg (an invalid build flag). Expect the aggregate `quake-ci` red, not skipped.
6. Break a test in `test_seismic_alert`. Expect red. Filter the suites so none run and expect red.
7. Open a workflow-only PR. Expect green.

## Phase B — cut-over
1. Follow the contract order exactly; record the saved `checks` array first.
2. After the contract's step 6, open a PR: only `quake-ci`, the release workflow where its path filter matches, and the default-setup checks run; `scripts/check_workflow_inventory.py` passes.

## Phase C — Keymind merge
1. Create `merge/keymind-trial` from `next` and merge the latest Keymind release into it.
2. Enable the suite; push or dispatch on the PR head; confirm the full suite has a result for the final commit; record the verdict; disable it again.
3. After reverting our skip, a diff of `.github/workflows/run-unit-tests.yml` against the Keymind tip is empty (blob 59d00855 if the old base).
4. Run the inventory drift check; compare the conflict list with the baseline.

## Phase E — version
1. Build both images with the candidate version; run `scripts/quake_release_manifest.py` and `tools/mota/pio_endf.py`.
2. Flasher: run the apps catalog build against a fixture or pre-release with the candidate pinned; confirm 1.18.0.2 appears under earlier versions and `ver` still parses.
3. On a device running 1.18.0.2 update by USB or Bluetooth DFU, and by manual on-air install; confirm the new `ver` text shows both versions.

## Phase F — seams
1. Trial-merge the newest Keymind release before and after and record conflicts. Build both images before and after; compare behaviour on hardware (telemetry shows the D7S and RAK1906, alerts fire, `peripherals.mode gps-only` keeps the rail on).
