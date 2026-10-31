# Quickstart: verifying each phase

## Phase A — the new check
1. Open a PR that changes only a Quake Repeater file. Expect `quake-ci` green, 15 minutes or less.
2. Open a docs-only PR and a workflow-only PR. Expect green, never pending.
3. Fault drill, one scratch branch each, expect `quake-ci` **red** (not skipped, not pending):
   - F1 an image fails to build.
   - F2 remove `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL` from the RAK4631 environment in `variants/meshamerica_quake/platformio.ini` (the 1.18.0.1 defect).
   - F3 remove the RAK3401 radio-power hold (its `-D RAK_3401` source in `variants/rak3401/platformio.ini`).
   - F4 break a test in `test_seismic_alert`.
   - F5 make the two `FIRMWARE_VERSION` values differ.
   - F6 set a version not above the highest `quake-v*` tag.
   - F7 break the stock smoke build.
   - F8 break one matrix leg, and separately cancel one dependency.
   - Also: run fewer than four earthquake suites (expect red).
4. Break the YAML syntax of `quake-ci.yml` on a scratch branch: expect no check at all (hang), confirming why observation precedes the requirement.
5. Open a `merge/keymind-trial` PR: expect `quake-ci` red until a completed `run-unit-tests` run exists for its head commit.
6. Tag a scratch commit `quake-v9.9.9.9` in a throwaway fork: the release must not publish unless the checks pass and the commit is reachable from `main`.

## Phase B — cut-over
1. Follow the contract order exactly; record the saved rule state (GraphQL result and REST checks) first.
2. After the contract's step 9, merge-back is a PR (the ritual); a direct push to `next` is rejected; a force-push to `next` is rejected; a PR with a red `quake-ci` cannot be merged by the owner.
3. After the contract's step 6, open a PR: only `quake-ci`, the release workflow where its path filter matches, and the default-setup checks run; `scripts/check_workflow_inventory.py` passes.

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
