<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/unit_test_workflow_fix_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Unit-test workflow follow-up - 2026-10-22

Baseline: `ab6412e73c1c36a53e2ecf08c79e3c223200cb3d` on
`keymindCascade`. The starting failure was
[workflow run 39886822765](https://github.com/mikecarper/MeshCore/actions/runs/39886822765).

## Failure and build scope

The run exposed three independent failures:

- RAK4631 Full Companion exceeded its existing application flash region by
  312 bytes.
- The Wio E5 Mini Repeater exceeded its existing application flash region by
  1,284 bytes.
- The Wio Tracker L2 GPS host fixture lacked the new battery-calibration
  capability in its mock base class, preventing six harness builds.

The earlier calibration report's direct PlatformIO builds did not use the
release wrapper. In particular, the wrapper links the Mini's runtime USB
packet logger and embeds release metadata and Cascade defaults. A direct
recipe passing its size check does not qualify that release artifact.

The relevant release builds must use these exact workflow commands, one
PlatformIO process at a time:

```sh
bash build.sh build-firmware RAK_4631_companion_radio_full \
  --firmware-version v1.18.0.1-halo-keymind-cascade-dev \
  --radio-preset usa-cascade-fixed --profile cascade --require-ota

DISABLE_DEBUG=0 bash build.sh build-firmware wio-e5-mini_repeater \
  --firmware-version v1.18.0.1-halo-keymind-cascade-dev \
  --radio-preset usa-cascade-fixed --profile cascade --allow-no-ota
```

The exact Mini release-wrapper build passed with 245,376 of 245,760 application
bytes used, leaving 384 bytes. Its runtime-memory gate also passed: 43,920 bytes
available against 32,288 bytes required. The application boundary and existing
16 KiB filesystem are unchanged. The complete board matrix is tracked in the
[unit-test workflow](https://github.com/mikecarper/MeshCore/actions/workflows/run-unit-tests.yml).

## RAK4631 Full Companion changes

The exact Full Companion release-wrapper build passed with 707,504 application
bytes before its EndF trailer. The stamped UF2 application occupies 707,584 of
712,704 bytes, leaving 5,120 bytes within the existing boundary. The runtime
memory gate passed with 81,228 bytes available against 74,576 bytes required;
the DFU handoff and 13 capability checks also passed. Reader, contacts,
Meshtext, sensors, Ethernet, SD support and LoRa OTA remain enabled. No flash
boundary or memory gate was relaxed.

The RAK4631 recipe explicitly selects its existing voltage-policy calibration
store. `RAK4631Board::begin()` loads that policy before application settings.
This lets the compiler omit an unreachable second `/battery_cal` backend while
retaining the existing 20-byte NVP2 record and its CRC. The store fails closed
if called before policy initialization. A missing or corrupt policy initializes
safe defaults; unsuccessful writes still return an error. Other board recipes
retain their generic calibration backend and fallback behavior. A typed setter
also avoids formatting a CLI command only to parse it again.

The linked ARM crypto checks passed both RFC8032 vectors. Key generation used
1,200 bytes of function-frame stack and signing used 1,904 bytes, within the
2,048-byte gate. These figures exclude caller, ISR and task stacks. Linked OTA
workspace checks passed four acquisition/release lifetimes without touching
the protected SD authentication range. Neither check is hardware qualification.
The linked Reader check passed all 879 references (885 calls), comparing
82,624 canonical bytes. Its maximum function-frame stack was 6,016 bytes;
the check also reserves 1,536 caller bytes within the 8,192-byte loop stack.
This excludes ISR/task stack and physical high-water measurements.

Beacon frequency and bandwidth parsing now shares the radio CLI's plain
decimal parser. This removes the general-purpose `strtof`/`strtod` conversion
code from the Full image and recovered 5,732 bytes in the final comparison.
Normal decimal settings, optional signs and decimal fractions remain available;
radio limits still reject invalid frequencies and bandwidths. Scientific and
hexadecimal numeric syntax is rejected, matching the ordinary radio CLI grammar.
NaN, infinity, whitespace and trailing junk are rejected as well.

Constant CLI error replies share their existing bounded formatter and prefix.
The existing command replies retain their text, capacities and termination;
new calibration replies use shorter wording while retaining the reading,
effective multiplier and persistence result.

The first rerun exposed an RS-232 packaging check that requires one complete
error-message literal as evidence that the merged command handler survived
linking. That handler retains its original literal. The capability check is
unchanged. Both Full and Reduced T114 Repeater release-wrapper builds then
passed all eight capability checks and their flash, RAM and DFU gates.

Calibration coverage includes three command/scaling tests, three store tests
(including four platform backends), 19 battery-forwarding tests and four power
policy compatibility tests. The actual nRF52 policy/store integration checks
pre-initialization rejection with present or absent storage, failed mounts,
corrupt policy CRC, saved calibration, unchanged NVP2 bytes, reset, bounds and
write/rename failures. A sentinel `/battery_cal` remains untouched throughout
the RAK policy test. These are host tests, not physical ADC qualification.

## Repeater diagnostic changes

Compact RX and TX packet records share one formatter. It emits the same
uppercase hexadecimal bytes, `R` or `T` prefix, and LF terminator. It retains
the existing bounded serial writer and `DROP` recovery marker.

When neither debug output nor packet-file logging is compiled, retry callbacks
avoid formatting discarded diagnostic strings. Flood-retry reachability still
updates for eligible successful echoes. Eligibility preserves the pending
bridge state, source mask, progress marker, target mask and route-hash checks.
The existing logged callback path remains intact.

The Repeater supplies its timestamp formatter whenever debug output,
packet-file logging or noncompact USB packet records need it. Builds with no
timestamp consumer inherit the base formatter without linking the unused
conversion.

These changes retain the Mini's release USB packet logger, calibration, routing,
host-service bridge, 50 neighbours and existing 16 KiB filesystem. They do not
add feature cuts or change flash and RAM qualification gates.

## Host regression results

Passed checks:

The complete native PlatformIO suite also passed all 1,897 test cases.

| Check | Coverage |
| --- | --- |
| `test/test_serial_packet_log/test_serial_packet_log.cpp` - 8 tests | Exact RX/TX bytes and LF; small FIFO; initially absent host; stalled host; 20 ms mid-record stall budget; truncation; drop counting and recovery markers. Run directly with GoogleTest, AddressSanitizer and UndefinedBehaviorSanitizer. |
| `test/test_mini_repeater_logging.py` - 3 tests | Actual Repeater RX, Dispatcher TX, packet codec and diagnostic callbacks across all eight carrier/management/file-logging combinations; maximum packet sizes; runtime logging gate; stalled writes; file-logging independence; host CLI and authorization contracts. |
| Flood-retry eligibility within that harness | Actual eligibility, bridge-heard mask and textual formatter agree for 576 source/target/progress/hash-size combinations in each feature variant. Missing state, empty/invalid paths, source-only echoes and progress-marker-only echoes do not refresh reachability. |
| Timestamp consumers within that harness | Production declaration and definition compile and return the expected formatter across all 16 debug/file/packet/compact combinations. |
| `test/test_cli_command_utils/test_cli_command_utils.cpp` - 62 tests | Includes three shared error-formatter regressions: exact output with literal percent directives; every capacity from zero through a complete reply; null destination at zero capacity; termination and untouched guard bytes; truncation at the 160-byte CLI boundary. Run directly with GoogleTest, AddressSanitizer and UndefinedBehaviorSanitizer. |
| CommonCLI dependency audit - 34 scripts, 166 tests | The 32 CommonCLI fixture suites and the Morse CLI and Beacon Manager suites pass after source-extraction fixtures include the real shared formatter. Includes RAK SD context handoff and its negative control, USB/ESP-NOW/RS232/UDP diagnostics, persistence, GPS, OTA, and the Morse FEM guard. |
| `test/test_beacon_manager.py` - 20 tests, included in the audit above | Actual Beacon Manager and extracted decimal parser accept ordinary signed/unsigned decimal tuples; reject exponent/hex notation, NaN/infinity, whitespace, trailing junk and out-of-range radio tuples. Existing scheduling, transactional storage and negative controls also pass. |

The Mini harness uses AddressSanitizer and UndefinedBehaviorSanitizer on Linux.
Radio and serial hardware are stand-ins. These results do not qualify physical
USB, RF, ADC readings, charging, bootloaders or installed devices.
