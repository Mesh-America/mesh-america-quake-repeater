# Seams: our edits to Keymind files

Every place the Quake Repeater changes a file that comes from Keymind, so a Keymind merge conflict is
a known, listed site and nothing is a surprise. Everything else we add is a new file of ours and cannot
conflict. Plan: `specs/001-keymind-separation/` (FR-010, Phase F).

Reference for the numbers: 11 modified Keymind files, 206 added lines and 4 lines that change existing
Keymind lines, measured against the last merged Keymind commit `03214a16df2bd09d3272dfb001d2d322c6740f60`.
Churn is the number of upstream commits touching the file since 2026-10-01 on
`keymind/keymindCascade` (tip `322e22a06`, 2026-10-30), counted in the maintainer's clone; counts
from a different clone or branch differ. Re-measure before relying on them.

Kinds: **adds** = only new lines; **edits** = changes an existing Keymind line (the likeliest conflict).

| File | Hunks | Lines | Kind | Upstream churn | Purpose | Generic? |
|------|-------|-------|------|----------------|---------|----------|
| `.github/workflows/run-unit-tests.yml` | 2 | +7 | adds | 332 | `if: ${{ false }}` skip of the stock-app compatibility test, with a comment (the live official app no longer matches the pinned bundle). **Revert inside the first Keymind merge window** (task qr-fgy.20). | no |
| `examples/simple_repeater/MyMesh.cpp` | 8 | +29 | adds (one splits an existing function) | 96 | All behind `#if ENV_INCLUDE_D7S` except one: the owner-info reply prints `FIRMWARE_PRODUCT` + version; `begin` calls `restoreClockFloor()` and `loadQuakePrefs()`; the CLI `else if` chain calls `handleQuakeCommand`; the main loop calls `checkQuakeAlert()` and `serviceClockFloor()`; `pendingWorkReason` stays awake while an alert is being sent. **Unguarded:** the flood-text sender is split so `sendGroupFloodText()` can be reused by the alert sender, which runs in stock builds too (covered by the stock smoke builds). | partly (`sendGroupFloodText` is generic) |
| `examples/simple_repeater/MyMesh.h` | 4 | +41 | adds | 67 | `#if ENV_INCLUDE_D7S` include of `SeismicAlert.h`/`ClockFloor.h`; the `FIRMWARE_PRODUCT` define beside `FIRMWARE_VERSION`; the `sendGroupFloodText` declaration (unguarded); and the alert and clock-floor members and methods (`quake_*`, `restoreClockFloor`, `handleQuakeCommand`, ...). The implementations are in our own `MyMeshQuake.cpp`. | partly |
| `mkdocs.yml` | 1 | +11 | adds | 38 | Navigation entries for the earthquake documents Keymind's docs build would otherwise skip. | no |
| `platformio.ini` | 1 | +3 | adds | 37 | `[env:native]` `build_src_filter` gains `D7S.cpp`, `SeismicAlert.cpp`, `ClockFloor.cpp` so the unit tests compile. Adjacent lines are also touched upstream. | no |
| `src/helpers/SensorManager.h` | 2 | +12 | adds | 6 | `SeismicReading` type and a `getSeismicReading` virtual on the base class. | yes |
| `src/helpers/sensors/EnvironmentSensorManager.cpp` | 5 | +83 / -2 | **edits** (2) | 14 | D7S driver integration into the telemetry manager. The two edited lines are the `#if ENV_INCLUDE_GPS || defined(ENV_INCLUDE_BME680_BSEC)` guard and its closing `#endif` comment, widened to `|| ENV_INCLUDE_D7S`. The rail-default test copies function bodies from this file using source anchors. | partly |
| `src/helpers/sensors/EnvironmentSensorManager.h` | 4 | +8 / -1 | **edits** (1) | 5 | `MAX_ACTIVE_SENSORS` raised by six sub-channels when the D7S is built in; `getSeismicReading` override; one `#if` guard widened to include `ENV_INCLUDE_D7S`. | partly |
| `src/helpers/sensors/WisBlockSharedPowerPolicy.h` | 3 | +5 / -1 | **edits** (1) | 2 | `SensorPower` rail hold (bit 4) enabled by `MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL`, so the `gps-only` mode does not cut the sensor rail. `KnownHolds` is the edited line. Covered by `test/test_quake_rail_default.py`. | yes (candidate to offer upstream) |
| `variants/rak3401/RAK3401Board.cpp` | 1 | +1 | adds | 3 | Drives `PIN_3V3_EN` as an output again (it may have been released to an input once a D7S was confirmed). | no |
| `.gitignore` | 1 | +6 | adds | 2 | Ignores the documentation site's build output. | no |

## How to use this on a Keymind merge

1. Before the merge, trial-merge the new Keymind tip in a throwaway worktree and compare the conflicts
   with this table. The last real merge (1.18.0.1) conflicted in `RAK3401Board.cpp`, `MyMesh.cpp`, a
   test and `run-unit-tests.yml`; a trial merge of the newest tip today has no conflicts.
2. The **edits** rows and `MyMesh.cpp`/`MyMesh.h` are where to look first.
3. After the merge, re-run `test/test_quake_rail_default.py` and `test/test_rak_gps_power.py`: both read
   or copy from `EnvironmentSensorManager.cpp`, and an upstream rename fails them loudly (an anchor
   assertion), which is intended.
4. Update this table when a seam is added, moved or removed.

## Candidates to offer to Keymind

The sensor-rail hold (`WisBlockSharedPowerPolicy.h`) and the `SeismicReading` base type are generic.
Whether to offer them is the maintainer's decision (task qr-fgy.32).
