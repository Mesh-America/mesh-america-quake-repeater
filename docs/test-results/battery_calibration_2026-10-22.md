<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/battery_calibration_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Shared battery ADC calibration validation - 2026-10-22

Final integration baseline: `94a3b7e568781533510721670af24c162804a5ca` on
`keymindCascade`, plus the calibration changes. Earlier builds and link
failures below used `af106a0ee9edd8ee0113b7b364290e0944245b86`; the final
integration section supersedes those results for the targets it names.
These checks do not constitute an installed-device or voltmeter acceptance test.

## Behavior and compatibility

- `battery calibrate <measured volts>` calculates the correction from the
  effective existing multiplier and the reported battery voltage.
- A reference is mandatory, with millivolt precision and no assumed battery
  chemistry or full voltage. A single correction must lie within 50% of the
  reported reading. Zero and saturated readings are rejected.
- `battery calibrate reset` saves the board's default conversion.
- Real ADC backends across ESP32, nRF52, RP2040 and STM32 opt into calibration.
  The Wio Tracker L2's external ADS1115 is included. Boards requiring an external
  divider still require that hardware; software does not add an input.
- Existing absolute coefficients for Heltec V4, V4 R8, RC32, Meshnology W12 and
  ProMicro retain their units and saved values. Other supported ADCs use a
  relative correction of 0.500-1.500, with zero restoring their factory scale.
- The nRF52 boot-voltage policy remains authoritative where available, and is
  applied once. Without that policy, ADC commands use the shared correction.
- Infrastructure roles restore their existing calibration preference centrally,
  including Repeater. Companion and Terminal use a checked, versioned
  `/battery_cal` record without changing their existing preference layouts.
- Failed saves attempt to restore the runtime multiplier. An uncertain
  publication returns an error rather than claiming persistence. Volatile
  recovery storage is not used for saving calibration.
- PMU/fuel-gauge readings, UART battery-module readings, raw-count test
  placeholders and boards with no battery-voltage measurement remain excluded.

## Host checks

All following checks passed using `TMPDIR=/var/tmp` (the machine's `/tmp` user
quota prevented compiler temporary-file creation):

| Check | Coverage |
| --- | --- |
| `test/test_battery_calibration.py` - 3 tests | Production parsing, meter correction, existing absolute coefficients, pack references, effective multiplier, reset, unsupported/zero/saturated readings, bounds, actual MainBoard scaling and nRF52 policy precedence. |
| `test/test_battery_calibration_store.py` - 1 test across four platform fixtures | ESP32, RP2040, nRF52 and STM32 transaction implementations; reboot restore, every single-bit record corruption, truncation, write failure, uncertain publication, reset, missing persistent storage and backup recovery. |
| `test/test_battery_forwarding.py` - 19 tests | Actual infrastructure setter, failed-save rollback, nRF52 policy fallback, and refreshed battery-based forwarding decisions. |
| `test/test_heltec_r8_external_power.py` - 1 test | Existing R8 power estimate still uses the calibrated voltage. |
| `test/test_stm32_companion_profile.py` - 21 tests | Existing ADC conversion and sampling remain exact at default calibration; memory/profile constraints retained. |
| `test/test_rp2040_application_capabilities.py` - 11 tests | Existing upload artifact and capability validation. |

The production calibration, store and forwarding harnesses use AddressSanitizer
and UndefinedBehaviorSanitizer. `git diff --check` also passed.

## Earlier firmware builds

Before integration, PlatformIO processes were run serially. Successful targets:

- `Heltec_v3_repeater`
- `Heltec_v3_terminal_chat`
- `Heltec_v3_companion_radio_usb`
- `RAK_3401_repeater`
- `RAK_3401_room_server`
- `RAK_3401_sensor`
- `RAK_3401_companion_radio_usb`
- `Xiao_rp2040_companion_radio_usb`
- `wio-e5-mini_companion_radio_usb`

That earlier Mini Companion occupied 228,832 of 229,376 application bytes:
544 bytes remained. This validates the current build recipe, not every possible version
string, optional feature combination or firmware target.

## Earlier STM32 flash blockers

The following targets compile but fail the linker flash limit. Both failures
were reproduced from an isolated, unchanged checkout of the baseline with the
same build recipes and compiler versions:

| Target | Baseline overflow | Calibration build overflow | Additional bytes |
| --- | ---: | ---: | ---: |
| `wio-e5-mini_repeater` | 1,168 | 2,852 | 1,684 |
| `wio-e5-mini_sensor` | 25,584 | 27,368 | 1,784 |

The calibration increase consists of code and constants; it did not introduce
additional floating-point runtime helpers in the Repeater. Filesystem and
application boundaries have not been moved, and no unrelated feature was
removed to conceal these build failures. These results apply to the earlier source baseline above, before the Mini
Repeater feature gates in `94a3b7e56`. The integration checks below supersede
that earlier Repeater result when a newer build succeeds.


## Final integration checks

After merging `94a3b7e56`, 69 distinct focused tests passed: 42 calibration,
platform-storage and related regressions, 19 battery-forwarding tests, and
8 Mini Repeater profile checks. The 23 calibration/store/forwarding tests
were rerun successfully after the final reply compaction. Both new calibration
suites are included in the unit-test workflow.

The first integrated Mini Repeater link exceeded flash by 432 bytes.
Disabling guessed branch probabilities in that target's existing size recipe,
sharing the existing save-failure replies, keeping the command key in constant
storage and shortening calibration replies recovered 808 bytes. Calibration,
routing, logging, 50 neighbours and the existing 16 KiB filesystem are retained.
No extra feature was disabled to make this image fit.

The final merged-source builds passed their flash and runtime-memory checks:

| Target | Application bytes used | Application limit | Free flash bytes |
| --- | ---: | ---: | ---: |
| `Heltec_v3_repeater` | 1,890,881 | 3,342,336 | 1,451,455 |
| `RAK_3401_repeater` | 559,616 | 815,104 | 255,488 |
| `wio-e5-mini_repeater` | 245,384 | 245,760 | 376 |
| `wio-e5-mini_companion_radio_usb` | 228,664 | 229,376 | 712 |

These small Mini margins qualify the stated recipes, not arbitrary optional
features or longer build metadata. The earlier Mini Sensor overflow remains
recorded above; that target was not rebuilt in this final integration campaign.
No physical ADC, voltmeter, charging or installed-device test was performed.

The later [unit-test workflow follow-up](unit_test_workflow_fix_2026-10-22.md)
records release-wrapper failures that these direct recipe builds did not cover.
