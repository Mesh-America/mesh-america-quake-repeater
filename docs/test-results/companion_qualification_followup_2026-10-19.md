<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/companion_qualification_followup_2026-10-19/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Mercerwood Companion follow-up, 2026-10-19

Across the retained baseline and selected normal HEAD tests, **9/11 Companions PASS and 2 FAIL**. Overall campaign status: **FAIL**, incomplete. A nonworking required axis counts as a board failure.

Baseline: `4e4f27a25a720c52ca0f5381b5e5834d75532cc6`. Selected normal HEAD refresh: `51538f0379076111c14d50b29618c5792e0490dc` (`v1.18.0.1-halo-keymind-cascade-dev-51538f03`). This report covers 11 Companions, with no new fleet-wide inventory or repeater qualification claim.

The branch advanced to `811b2d7232aff86fd13075cee9ff6ac6471d2b6c` during the campaign. Its four subsequent radio changes are outside the measured sources and have not been hardware-qualified by this report.

Later baseline RF tests closed the V4.3 and XIAO ESP32-S3 gaps: each exchanged an exact zero-hop DEV datagram in both directions with RAK 4631, packet counters advanced, owned channels were cleared and radio leases restored. A bounded transition drain preceded the unchanged strict handshake; it was not itself a qualification pass. Earlier setup failures remain in the record.

The retained 4e campaign now has 9/11 Companions passing all three required axes: 10 USB passes, 9 BLE passes and 10 RF boards through 9 two-way links. T1000-E BLE and XIAO nRF52 remain failures.

| Companion | Qualification source | USB | BLE | RF | Overall |
| --- | --- | --- | --- | --- | --- |
| Heltec V4.3 | 51538f03 | PASS | PASS | PASS | PASS |
| LilyGo T-Deck | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| RAK WisMesh Tag | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| Heltec MeshPocket | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| SenseCAP Indicator | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| RAK 4631 | 51538f03 | PASS | PASS | PASS | PASS |
| Heltec V3 | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| Seeed XIAO ESP32-S3 | 51538f03 | PASS | PASS | PASS | PASS |
| Seeed XIAO nRF52 | 4e attempted; runtime unverified | FAIL | not runnable | not runnable | FAIL |
| Heltec T096 | 4e4f27a2 retained | PASS | PASS | PASS | PASS |
| Seeed T1000-E | 51538f03 | PASS | FAIL | PASS | FAIL |

The six retained baseline boards have not been requalified at the new source. Of the four refreshed boards, three passed every required axis; T1000-E failed BLE. Selected normal HEAD USB passed 100 query cycles and 10 reopen checks on V4.3, XIAO ESP32-S3, RAK 4631 and T1000-E. Each also passed owned-contact cleanup, warm reboot and radio2 checks, with 18/18 ports closed, zero stable binary framing rejects and clean final core flags. ASCII-to-binary setup and deliberate reboot transitions are recorded separately.

HEAD RF passed all three RAK hub links (V4.3, XIAO ESP32-S3 and T1000-E), one exact DEV datagram in each direction, with clean channel/lease cleanup. RAK also passed three 30-second normal BLE sessions, matched its USB identity/full version and disconnected cleanly.

V4.3 and XIAO ESP32-S3 initially failed normal HEAD BLE. Both traces show a successful exact-target connection followed by HCI encryption status 0x06, PIN or Key Missing, consistent with obsolete host keys after full ESP erase. A separately gated repair removed one proven target host bond each; it changed no other bond, reset no adapter and did not qualify BLE. V4.3 subsequently passed all three normal BLE sessions with USB identity/full-version matches, clean core flags and final disconnects. XIAO ESP32-S3 also subsequently passed all three normal BLE sessions with the same identity, version, core-state and disconnect checks.

The original V4.3, XIAO ESP32-S3 and RAK flasher commands returned 1 and remain failed workflow records. The ESP logs contain successful image-hash verification before native USB reset waits expired. Later exact-source clean USB qualification is separate evidence of working application runtime; it does not rewrite those return codes.

T1000-E BLE remains FAIL. Two normal HEAD discovery attempts, an MCU LDO trial, restored auto/DC-DC policy, a HEAD diagnostic image and the older cdacf670 reference all failed to produce the required current matching advertisement. The older Page Timeout pairing failure remains historical evidence rather than the reason for these discovery failures. No direct-link failure is counted where no connection was attempted.

The diagnostic firmware reported SoftDevice/interface readiness and advertising activity, with advancing loop timestamps, but those readbacks do not prove an over-air advertisement. The regulator comparison establishes no DC-DC cause. Normal HEAD was restored after the older-reference test; fresh USB evidence matched the same public identity, normal full version and original MCU/radio auto policy (both active DC-DC). Diagnostic collection does not count as normal BLE qualification.

A final read-only check at 2026-10-20 02:13:35 UTC confirmed normal HEAD on T1000-E, Bluetooth enabled, clean core flags and the original regulator policies. The active MQTT gateway still owned its original RAK 3401 primary USB interface; that port was not opened by the check.

C2 bootloader installation was verified at 2026-10-19 19:20:57 UTC. The same T1000-E old-reference trace at 20:04:22 UTC subsequently recorded one secured connection, with clean core flags; that trace did not qualify the full BLE test. The same older reference now fails advertisement discovery, so the failure is not isolated to the latest application build. All eight required C2 installation baselines remain separate from application qualification. Package manifest CRC validation is not an installed-flash CRC readback.

XIAO nRF52 is FAIL. The normal application transfer succeeded, but normal USB/runtime never qualified; BLE and RF cannot currently run. Its latest passive candidate-port capture returned protocol error -71 and zero bytes for all 24 device-descriptor reads and all eight address-setting attempts. No configuration or CDC request occurred, and no original UID or firmware mode was verified in that capture. This establishes failure before USB configuration, without assigning a cable, power, host, bootloader or application cause.

The passive observer issued no deliberate reset, serial open or image write. The kernel automatically issued 35 port-reset requests and two port-power off/on request sequences; accepted requests do not measure downstream power. The diagnostic image and staged 40b source hardening were not installed, so neither is claimed as a hardware fix.

These are finite campaign checks. USB covers the specified query/reopen/CRUD/warm-reboot/radio2 checks; BLE covers three 30-second sessions; RF covers zero-hop DEV datagrams and cleanup. They do not establish phone interoperability, cold boot, RF range, text delivery or every firmware feature.

Original histories remain in [the earlier campaign report](hardware_validation_mercerwood_1_18_0_1_2026-10-19.md): Tag recovery, V3 discovery retry, Pocket watchdog observations, earlier setup aborts and failed XIAO runtime recovery. No earlier trial or physical-presence history is deleted.

[Machine-readable results](companion_qualification_followup_2026-10-19.safe.json) contain source-bound board records and SHA-256 evidence digests.

The unit-test workflow passed all 12 jobs for source `51538f03`: [GitHub run](https://github.com/mikecarper/MeshCore/actions/runs/39350014767).

Later selected-board evidence, the T1000 bootloader button correction and the final Full Companion USB/BLE results are recorded in [the diagnosis follow-up](companion_qualification_f807_followup_2026-10-19.md). The T1000 BLE and XIAO nRF52 failures remain open.

Later accepted measurements are recorded in the [2026-10-20 fleet
qualification](hardware_validation_mercerwood_1_18_0_1_2026-10-20.md).
Results and failures above retain their original firmware sources.
