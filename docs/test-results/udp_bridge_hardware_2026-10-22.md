<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/udp_bridge_hardware_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Five-board WiFi UDP bridge hardware qualification, 22 October 2026

**PASS for the tested Full Repeater configuration.** Five physical ESP32 boards
passed the directed UDP matrix, rejection checks, reconnects, software-reboot
persistence and physical LoRa forwarding through eight configured UDP peers.
All final images use
[source `36d9735e5`](https://github.com/mikecarper/MeshCore/commit/36d9735e5539656a31b648eff32cae6b99576500).
Independent raw-packet and cleanup audits passed before consolidation of the
[machine-readable results](udp_bridge_hardware_2026-10-22.safe.json).

Physical coverage combines two disjoint scopes: twelve accepted passing cases
from failed run05 and eighteen from passing run07. Run05 remains failed; the
first twelve cases were not repeated. Failed run06 sent no data and remains
preserved separately.

## Coverage and results

| Check | Completed result |
| --- | --- |
| Canonical Full builds and installation | Five boards; capability and memory gates passed; no feature reductions |
| Directed UDP probes | 300/300 across 60 directions, five probes each |
| Security rejections | 20/20: replay, bad authentication, unknown endpoint and malformed frame on each board |
| Recovery | WiFi reconnect and saved UDP-off choice passed on all five |
| Qualified software reboots | Five restarts, retained configuration and 20/20 fresh probes |
| Physical LoRa delivery | 25/25 exact application receipts, five per ingress board |
| UDP-off negative controls | 5/5; none crossed the frequency gap |
| Independent copy audit | 100 physical-peer copies and 100 Pi-endpoint copies; zero UDP transit |
| Final cleanup | Five boards quiet, original RXPS restored and owned fixture stopped |

The matrix covered 20 board-to-board, 20 board-to-Pi and 20 Pi-to-board
directions. Initial station readiness was observed on the first read-only poll
for every final image. Each board had 23 continuity samples spanning at least
1,043 seconds, with advancing uptime and no new
latched error bits. The reboot qualification used deliberate software restarts,
not cold power cycles. Identity, exact firmware/model, shared secret, UDP port
and all eight peers persisted; eight authenticated sessions returned.

## Boards and builds

| Board | Selected Full environment | Modeled internal-memory margin |
| --- | --- | ---: |
| Heltec V3 | `Heltec_v3_repeater_observer_mqtt` | 352 bytes |
| Heltec V4.3 OLED | `heltec_v4_repeater_observer_mqtt` | 4,720 bytes |
| LilyGo T-Deck | `LilyGo_TDeck_repeater` | 53,632 bytes |
| Seeed XIAO ESP32-S3 WIO | `Xiao_S3_WIO_repeater_observer_mqtt` | 9,960 bytes |
| SenseCAP Indicator LoRa N8R8 | `SenseCapIndicator-LoRa_repeater` | 1,904 bytes |

The shared V4 target detects the V4.3 FEM at runtime. The Indicator tested here
has 8 MiB flash and OPI PSRAM. Its separate 16 MiB/QSPI N16R2 recipe is not
interchangeable and was not physically qualified. Existing display support
was retained in the repeater recipes. Build receipts bind source, recipe and
application/merged-image hashes, verify both OTA slot capacities, and report
empty feature-reduction lists. Slot checks do not qualify an OTA installation.

## Physical method and operating conditions

Each ESP32 had four other physical ESP32 peers plus four controlled Pi UDP
endpoints: eight configured destinations, not eight physical peer radios.
All joined an existing WiFi network as stations. MQTT, ESP-NOW and RS232 bridges
were disabled. UDP used the existing bridge shared secret without another
password; authentication does not encrypt the traffic.

Physical trials used **917 MHz ingress and 918 MHz egress, SF7, 62.5 kHz
bandwidth, CR5, preamble 32 and TX 2 dBm**. Radio2 and LoRa RX powersaving were
**off during packet trials**. Each ingress received one UDP-off control and
five fresh positive frames. T096 and Tag served as the physical source/sink
witnesses. Their different frequencies prevented a direct LoRa delivery from
substituting for bridge forwarding. The Pi did not inject mesh data, and each
accepted trial had exactly one physical send with no application retry.

The independent audit checked source counters, exact application bytes and
sequence, actual Pi event membership, four matching Pi copies per positive
frame, all four physical-peer copy observations, and exactly one designated
LoRa egress. Physical-peer observations include explicitly accounted duplicate
receipts. No receiving UDP peer re-exported the frame to UDP. Before each role,
the harness waited at least 65 seconds after radio activation and proved at
least two seconds of stable RF/UDP counters.

Historical watchdog flags and cumulative receive errors were retained in the
raw baseline. V3 had four receive errors recorded during setup; no measured
packet added one. A previously latched bit 8 was admitted only with explicit live
RX history, matching diagnostic/physical error counters, soft-only recovery
and an empty queue. This does not attribute every historical flag to idle
maintenance. Every measured packet required unchanged latched flags and
soft/hard recovery counters, **zero new physical receive errors**, and **zero
new witness receive errors**. There was no blanket exemption for bit 8.

## Runtime memory and final state

These measured internal-memory values are bytes. The boot minimum is the
firmware low-water counter read at cleanup, not a minimum across every earlier
boot. Modeled build margins above are separate capacity estimates.

| Board | Before cleanup free | Reported boot minimum | After cleanup free |
| --- | ---: | ---: | ---: |
| V3 | 74,400 | 42,652 | 114,800 |
| V4.3 | 81,164 | 76,028 | 106,528 |
| T-Deck | 151,584 | 145,812 | 176,996 |
| XIAO ESP32-S3 WIO | 136,464 | 131,304 | 161,844 |
| Indicator N8R8 | 106,644 | 101,672 | 132,036 |

All final core and memory queues were zero. V3 had no PSRAM; the other boards
reported it. Cleanup restored all five original RXPS-on profiles, disabled
UDP/repeat/logging, cleared all eight test peers, selected bridge source TX and
left WebConfig inactive. Identity, saved radio, WiFi/secret and CPU power policy
were preserved. No CPU-clock setter was issued; actual CPU-frequency readback
is not claimed. Cleanup performed no flash, erase, reboot, stats clear or
intentional data send. The final owned fixture stopped once, following the
separately receipted stop of its predecessor.

## Fix and preserved failures

The original V4.3 recovery failure exposed UDP/WebConfig station ownership:
an unused automatic recovery AP prevented the saved station connection from
returning. `36d9735e` fixes that handoff while preserving explicit setup/OTA
ownership and saved UDP-off intent. Twelve native ASan/UBSan tests and
independent review preceded the five final builds; the final physical matrix
then passed the formerly failing recovery sequence. The UDP protocol did not
change.

Earlier failures were retained rather than replaced by later passes. The
[history hash index](udp_bridge_hardware_2026-10-22.history.safe.json) records
actual receipt outcomes and separate preserved archives.

| Preserved attempt | Outcome and disposition |
| --- | --- |
| Baseline matrix01 | V4.3 recovery failed; XIAO recovery was not run. Final `36d9735e` matrix02 passed all five. |
| Initial Indicator join | One WiFi off/on joined with the same saved credentials; separate root cause remains unproven. |
| RF02 / RF03 | Zero data trials: busy witness setter, then Pi USB/Ethernet host fault. Recovery03-01 readback adapter failed; corrected recovery03-02 passed all seven devices. This was not measured RF packet loss. |
| RF04 | One accepted negative request; automatic OTA bootstrap traffic changed the strict negative-control counters. A bounded bootstrap/quiet wait was added. |
| RXPS restore01/03; setup04 | V4.3 restoration rejected; setup04 separately failed on a startup queue. Restore02 and final cleanup restored all five original profiles. Ordinary V4.3 RXPS is supported. |
| RF05 | Twelve strict passes, then preflight stopped on a latched watchdog flag before V3 data. Overall failed status retained. |
| RF06 | Zero data; historical-baseline gate incorrectly required current last-RX age and absolute zero cumulative errors. Run07 retained baselines and enforced zero new errors per packet. |
| Fixture and offline adapters | Original fixture ended during the host fault; two explicit RF fixture replacements preserved identical configuration. Exact getter/model adapters were corrected without firmware changes or repeating accepted packets. |

Full CI is separate evidence. Test-only fixture repairs were pushed in
`8da70b84d` and `52a36c89d`; focused tests passed. At report preparation,
[CI run 39869220511](https://github.com/mikecarper/MeshCore/actions/runs/39869220511)
had twelve successful non-main jobs while its main test was still running;
full CI success is not asserted here.

## Evidence and limits

The consolidated result binds all 32 opaque private-file hashes, both independent
audits and the disjoint campaign receipts. Its SHA-256 is
`f6a384cc496f8c1a457ddd10df581925ca0a444ebad51fec65155fed3e68a4f3`.
The final private archive SHA-256 is
`22adb7f49b6c1650248f63acf9f6f9a70971e5c7b3c3e17400c4b28803eb4206`.
That tar covers final evidence; earlier failures remain in separate preserved
archives identified by the history index. Private contents are not published.

The later noise-floor telemetry change in `f4ade738d` was not installed on
these radios and is outside this hardware result.

This qualifies Full Repeater UDP forwarding under the stated radio/power
conditions. It does not qualify other firmware types, every power/radio
profile, eight physical peers, AP-mode UDP, arbitrary router/VLAN policies or
client-isolation bypass. Simultaneous bridge backends, BLE, physical firmware
OTA application, cold starts, maximum load and long-duration soak remain
outside this campaign.
