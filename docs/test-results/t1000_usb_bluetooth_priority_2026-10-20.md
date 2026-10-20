<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/t1000_usb_bluetooth_priority_2026-10-20/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# T1000-E USB priority, 20 October 2026

Source: `ac0daf3cef31a13163d469c1fd538c06708fe05a`.

T1000-E Companions now stop Bluetooth advertising and disconnect the Bluetooth
client whenever a USB data host is enumerated. This implements the requested
USB-priority policy after the [simultaneous USB/BLE investigation](companion_qualification_f807_followup_2026-10-19.md)
did not establish a reliable coexistence fix.

USB priority does not depend on an open serial application or DTR. A charge-only
supply does not acquire priority. Bluetooth is requested again after the data
host has been absent for 500 ms, preserving manual-off and wireless controls.
The policy does not change saved preferences, pairing credentials or identity.
It applies to the T1000-E Bluetooth and Full Companion recipes.

| Check | Result |
| --- | --- |
| Full Companion build, capability markers, runtime RAM and application-only image bounds | PASS |
| Bluetooth Companion build, capability markers and application-only image bounds | PASS |
| Priority, startup/wake, manual controls, reply routes, bus-reset hold and timer wrap | Six host tests PASS |
| Existing Bluetooth preference/CLI and wireless control tests | Eleven host tests PASS |
| nRF52 BLE regressions, including late connect after disable | 42 tests OK; eight emulator-dependent tests skipped |
| Contact-stream concurrency | Two host tests PASS |
| Hosted documentation links | Seven Python tests and JavaScript checks PASS |
| Install Full on the exact Pi-connected T1000-E | PASS; application only, identity unchanged |
| USB runtime and saved on/off commands while paused | PASS; status reports `bluetooth off (USB data connected)` |
| Saved on during USB priority | PASS; command acknowledges saved on while remaining paused |
| Twenty-second BLE scan with USB enumerated and serial handles closed | Zero target events among 100 scan callbacks |
| Post-test USB readback | PASS; same identity/version, zero core flags, zero recorded crashes |
| Physical unplug, BLE recovery and reconnect qualification on this build | Pending user unplug |
| USB insertion during an established BLE session | Host regression covered; hardware check pending |
| Charge-only and cold-boot behavior on this build | Host policy covered; hardware checks pending |

The installed version is
`v1.18.0.1-halo-keymind-cascade-dev-ac0daf3c (Build: 20-Oct-2026)`.
Its application ZIP SHA-256 is
`64e09ff2eb8b5e3228f656c7ea99b000c053736b8a020b7eab1429b4d00ab43f`.
The bootloader and SoftDevice were not changed. All opened USB ports were
closed, with no framing rejects in the recorded runtime checks. The original
saved-on Bluetooth choice was restored after the temporary on/off test.

This verifies USB-priority behavior, not simultaneous active USB/BLE, complete
T1000-E feature qualification or qualification of the other campaign boards.
Historical battery and wall-power passes belong to their original builds.
[Safe evidence summary](t1000_usb_bluetooth_priority_2026-10-20.safe.json)
records the current source and artifact bindings.

Later accepted measurements are recorded in the [2026-10-20 fleet
qualification](hardware_validation_mercerwood_1_18_0_1_2026-10-20.md).
Results and failures above retain their original firmware sources.
