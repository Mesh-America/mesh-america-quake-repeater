<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/companion_qualification_f807_followup_2026-10-19/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Mercerwood Companion diagnosis follow-up, 2026-10-19

Overall status: **FAIL, incomplete**. Across the selected measured sources, **1/2 Companions PASS, 1 FAIL**. RAK 4631 passed USB, BLE and two-way LoRa at f807. T1000-E passed latest normal Full USB but remains **FAIL** because BLE has not qualified. XIAO nRF52 remains a carried-forward failure.

Both selected boards first returned to Full `f80751354ffc530461e87109ced4f575d3950a52`. T1000 subsequently received normal Full `42f7df082fc4c7362ecd5c18c8644ab25b51b9e9`, version `v1.18.0.1-halo-keymind-cascade-dev-42f7df08`, after the corrected bootloader. Its ZIP SHA-256 is `7fac141e40183ada315f70b296583eaf854fd819c76fbd896a1f0f2e4a405e5b`. Checks ran on October 20 UTC during the October 19 local campaign.

| Companion | Source | USB | BLE | LoRa | Overall |
| --- | --- | --- | --- | --- | --- |
| RAK 4631 | f8075135 | PASS | PASS | PASS | PASS |
| Seeed T1000-E | 42f7df08 | PASS | FAIL | not requalified; f807 passed | FAIL |
| Seeed XIAO nRF52 | prior failure retained | FAIL | not qualified | not qualified | FAIL retained |

This is a selected-board follow-up, not a 13-radio fleet qualification. Repeaters were outside scope. Earlier mixed-source results remain in [the previous follow-up](companion_qualification_followup_2026-10-19.md).

Before the bootloader comparison, each f807 USB run passed 100 query cycles, 10 reopens, radio2 checks, owned-contact CRUD, persistence through warm reboot and contact cleanup. Each closed 18/18 ports with clean final core flags and zero stable binary prefix discards or invalid lengths. ASCII setup and intentional reboot recovery remain separate transition evidence.

RAK BLE passed three 30-second sessions with USB-bound identity, board, full version, NUS services and getters verified. Uptime advanced, flags stayed clean and each session disconnected. LoRa passed an exact zero-hop DEV datagram in each direction between RAK and T1000, with packet-counter checks, owned-channel cleanup and restored radio leases. These finite checks do not establish phone interoperability, range or text delivery.

T1000's original f807 BLE run failed current-advertisement identity binding with zero sessions. A later 90-second Pi follow-up also completed none despite Bluetooth enabled, stealth off and clean USB core flags. The unpaired BlueZ cache retained `T1000-BLE-PROBE` while USB verified normal f807 and its configured MeshCore name. Cached naming may affect filtering without a current scan response; it proves neither the BLE cause nor a duplicate address or working connection.

Minimal BLE-only, payload/timing, clock-request, transmit-power and LFRC images were diagnostic probes, not Full acceptance. The LFRC probe used an explicit RC configuration and valid vectors; this does not establish a defective crystal or justify changing production clocks. Advertising/HFXO readbacks do not measure RF accuracy or prove over-air packets.

The official upstream `companion-v1.18.0` T1000 BLE reference had matching ZIP/UF2 application bytes, base `0x27000` and SoftDevice requirement `0x0123`. Its bounded Pi scan did not find the required current advertisement. Phone visibility was insufficiently bound to name/time. This application-only experiment retained the same bootloader/SoftDevice and cannot isolate them. Normal Full was restored. Reference ZIP SHA-256: `79e53c2ce13521ccda5db3621a68f79728d2f241c3a8345e4107b7ae6b5a374d`.

Installed S140 7.3.0 readback CRC `733639BD` matched the package bytes, also identical to Seeed's recovery package SoftDevice. That checks the covered image, not RF operation. C2 installation preceded a historical secured diagnostic link that never completed full BLE qualification.

A separate DFU defect was corrected in bootloader `c0c421184a3cf1ca66b40b055101f20b8c587e26`: active-high P0.06 had been configured pull-up/active-low, with RESET/P0.18 treated as another button. The correction adds qualified three-second hold/USB-first recovery while retaining explicit-request latency and other boards' two-button behavior. Eleven actual-function host tests, 13 DFU-entry checks and T1000/T096/T114 cross-builds passed. See [candidate PR #1](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/pull/1) and [upstream polarity evidence](https://github.com/meshtastic/Adafruit_nRF52_Bootloader_OTAFIX/commit/0f415c3ee26816ad52a7587b3d6cdd30547987ec).

The reviewed combined bootloader transfer returned 0, but its installer stopped when the MSC disk was unavailable. That failed workflow remains failed. Later exact-device public INFO verified model `Seeed T1000-E for Meshtastic`, Board-ID `nRF52840-T1000-E-v1` and version `TEST_0x02040C01`. Package CRC `6BA4D206` was validated offline; installed CRC was not exposed. Combined ZIP SHA-256: `8db09e6b7f253b1e54aae754220f0d1053d369c07bff299a26b384233de6e234`.

Separate f807 application programming and its adapter command both returned 0. An independent USB check passed 15 queries/two reopens, closed 5/5 ports and verified normal f807, the same public identity, clean framing and zero core errors. With the corrected bootloader and same f807, an explicit-address 90-second BLE attempt still failed advertisement binding with zero sessions. No BLE fix or bootloader cause is established.

Final normal Full 42f7df08 installation succeeded. Its fresh USB run passed 100 queries, 10 reopens, owned-contact CRUD/cleanup, warm reboot and radio2 checks, with 18/18 ports closed, zero stable framing rejects and clean core flags. Its normal 25-second BLE discovery still failed with zero sessions. LoRa was not requalified at 42f7df08; the earlier f807 RF pass remains source-bound.

Combined serial delivery avoided legacy UF2 scratch `0xE0000..0xEA000`, which overlaps internal ExtraFS. Its staging and f807 restore remain below ExtraFS. No filesystem-preservation claim replaces runtime checks.

A subsequent 90-second scan by the independently verified Bluetooth address also failed to reach a connection on normal Full `42f7df08`.

After the user reported a reset, USB was present at preflight. Fresh USB passed 15 queries/two reopens on the same normal Full image. A 90-second Pi scan completed zero BLE sessions and captured zero target advertisements among 643 advertising event blocks. A separate 30-second passive scan captured one target advertisement among 3,375 blocks; direct public-service discovery timed out. A temporary saved random address produced two primary advertisements but no usable connection. Factory-default addressing was restored and verified over USB; Bluetooth remained enabled with clean core flags. No host bonds were removed. These are post-reported-reset observations, not a verified cold or battery-only test.

Fresh normal RAK and T096 USB/BLE controls passed on the Pi. An independent RAK nRF52 central diagnostic, version `v4.1`, then passed a single public ATT/NUS metadata comparison against the USB-bound T096. It read the expected public GAP name, recorded no security activity, and disconnected cleanly. The unchanged T1000 Full image then supplied a current primary advertisement at -63 dBm, but its one attempted connection ended with `0x3E` before any NUS metadata or public read succeeded. The observer's uptime and watchdog counters advanced, with no late connections or security events; scanning and connections stopped cleanly. A central connected event does not prove the peer received its connection request; [Nordic describes this initial-exchange failure](https://devzone.nordicsemi.com/f/nordic-q-a/96512/ble_gap_evt_connected-followed-by-ble_gap_evt_disconnected-with-0x3e-reason).

This comparison strengthens a T1000-specific link finding across two central implementations. It does not identify a faulty component or establish a bootloader cause. That comparison did not reach pairing or password exchange. The temporary central is not Companion qualification. Its initial v4 scan-unit error was corrected before either trial; live v4.1 status verified a 3,000-unit, 30-second scan configuration. The RAK was restored to the exact normal Full f807 ZIP and passed fresh 15-query/two-reopen USB and one 10-second BLE session with the same public identity. T1000 remains **FAIL**. Its pin assignments match [Seeed's T1000-E hardware list](https://wiki.seeedstudio.com/t1000_e_intro/); no further pin change is justified by this evidence.

A later controlled Bluetooth off/on test kept USB management open and had the Pi client scanning before enable. Unlike the earlier fixed-duration discovery, this client attempted pairing 49 ms after its first current target advertisement, which arrived 84.331 seconds after the on request. This time the trace proves bidirectional SMP and ATT exchanges and a passkey request. The supplied PIN matched the active USB-reported PIN and the user's expected PIN. The link then ended with HCI Connection Timeout `0x08`; BlueZ reported Authentication Canceled. No completed bond or Companion session, explicit PIN rejection, or stable-link pass is established. The parent evidence exporter subsequently failed to parse a traceback as JSON; that workflow failure remains recorded, separate from the independently analyzed radio trace. A further exact-address ATT connection was requested while Bluetooth was off, with its kernel scan already pending before enable. It failed initial establishment with `0x3E` and read no NUS service. Bluetooth was restored on, with the same factory-address policy, stealth off, monotonic uptime and clean core flags. Firmware and host bonds were unchanged. These tests refine the failure to an unstable link that can sometimes reach pairing; T1000 remains **FAIL**.

A subsequent application-only isolation test installed two small public-NUS echo diagnostics built against source context `56b4d72e6`. They omit Companion, LoRa, GNSS-driver and sensor processing, retain the board/framework/SoftDevice/bootloader, and feed every active watchdog channel. Both builds passed memory/vector/package checks and exact-device serial DFU/runtime verification.

| Diagnostic | Observation | Result |
| --- | --- | --- |
| Minimal external LF crystal, 20 ppm | No target advertisement in 60 seconds; uptime advanced 62.215 seconds with watchdog feeds advancing | No connection or echo |
| Same minimal app, internal LF RC, 250 ppm | One target advertisement after 42.138 seconds at -60 dBm; connection attempt timed out; uptime advanced 59.209 seconds with watchdog feeds advancing | No connection or echo |
| Normal Full with four-second initial supervision timeout from RAK central v4.2 | Current target advertisement at -62 dBm; initial connection establishment failed with `0x3E` before public GATT reads or security activity | FAIL |
| T096 control with the same central parameters | Public NUS service/characteristics and expected GAP name read successfully | Diagnostic control PASS |

The controller reported the configured 48.75 ms interval, zero latency and four-second initial timeout for both central trials. A central connected callback does not prove T1000 receipt of its connection request; the failed initial exchange does not test pairing on an established four-second link. The Pi's earlier attempt to extend a live connection saw no target advertisement in 90 seconds, so no update was applied. A host-only HCI-filter padding error was corrected before that valid trial and remains recorded separately.

These results make it less likely that the Companion workload or the external low-frequency crystal alone explains the failure. They do not distinguish common framework/SoftDevice behavior, the high-frequency radio clock, power or RF hardware. Both minimal images were removed. Normal T1000 Full `42f7df08` was restored and passed 15 USB query cycles/two reopens with the same public identity. The test RAK returned to its exact normal Full f807 image and passed 15 USB query cycles/two reopens and one 10-second secure BLE Companion session with the same identity. The four-second comparison had T1000 USB present before and after; it was not a battery-only test.

Cold boot, physical battery-only BLE, complete phone/feature testing and fleet qualification remain untested. Longer USB-powered scans are not battery tests. [Safe JSON](companion_qualification_f807_followup_2026-10-19.safe.json) retains source bindings, workflow distinctions and evidence digests without device secrets or raw addresses.
