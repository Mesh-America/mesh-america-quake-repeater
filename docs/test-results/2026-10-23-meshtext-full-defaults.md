<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/2026-10-23-meshtext-full-defaults/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Full Companion Meshtext defaults, 2026-10-23

The T1000-E image originally installed on MercerWoodMesh did not expose
`get mt.status`. Its LR1110 board was outside the former default-enable gate.
Commit `127d1bec2` enables Meshtext for supported ESP32/nRF52 Full Companions,
independently of board/chip-name macros. Explicit overrides, ESP-NOW primary
exclusion and actual modem/profile validation remain in force.

## Physical interoperability

The T1000-E and Heltec V4.3 OLED ran Full Companion `127d1bec2`. The independent
witness was XIAO S3 WIO running official Meshtastic `2.7.26.54e0d8d`, hardware
model 81, controlled using SDK 2.7.11. Its official radio pins match the WIO
carrier. No nRF52 bootloader or SoftDevice was replaced for this campaign.

Meshtext used US LongFast: 906.875 MHz, BW250, SF11, CR5, public AQ key,
16-symbol preamble. Both Companions retained a 917 MHz/BW62.5/SF7/CR5 primary.
No test transmissions used 910.525 MHz. Generic retries were off, MT hop limit
was 1, and the stock witness was CLIENT_MUTE with MQTT disabled.

| Check | Independently received |
| --- | --- |
| T1000-E to V4 and stock witness | 5/5 at each receiver |
| V4 to T1000-E and stock witness | 5/5 at each receiver |
| Paced stock witness to both Companions | 3/3 at each receiver |
| Primary MeshCore, T1000-E to V4, MT still active | 3/3 |
| Primary MeshCore, V4 to T1000-E, MT still active | 3/3 |

Each of the three paced stock messages increased V4 Meshtext RX by one and
completed TX by one with `mt.rebroadcast on`, without an originated V4 message.
T1000-E TX remained unchanged with rebroadcast off. This verifies forwarding
activity; it does not establish an isolated, exclusively one-hop route.
V4 was left with `mt.rebroadcast on`. The temporary primary test channel was
removed after its six messages.

The initial sweep used 14-second observation windows and reported missing
messages. One appeared in the next window. Follow-up sends, paced 45 seconds
apart, reached both receivers after 9.6, 15.2 and 20.6 seconds from the local
stock queue request. Short-window misses therefore are not a reliable RF-loss
measurement and are not counted as successful deliveries. Dual-profile RX
remains time-shared; these checks do not promise lossless simultaneous reception.

Private raw evidence and identity-bound flashing logs are retained under
`/home/mesh/hwtest/mt-longfast-20261023` and the matching Pi directory.

### Post-campaign device state

The T1000-E and V4 were subsequently installed with pushed source `5aac9570b`.
Both answered their identity/settings checks and exchanged Meshtext messages
in both directions. V4 retains `mt.rebroadcast on`.

Restoring the stock XIAO S3 WIO witness remains unfinished. Its original USB
serial identity still enumerates, but CDC control requests fail with protocol
error 71 and the stock serial API does not complete configuration. Software
ROM-entry requests have not produced a verified ROM connection; no restore
write was attempted without one. This is a recovery failure and is not counted
as a qualified final MeshCore installation.

## Build and memory checks

The T1000-E, V4.3 Full and Heltec V2 Full images passed linking, executable
Meshtext capability checks and memory/flash budgets. At merged source
`170c1761d`, XIAO C3, C6, nRF52, S3 WIO, Heltec CT62 and Tracker V2 Full also
passed. Compile qualification is separate from physical board qualification.

The first C3 build failed the unchanged runtime heap guard. Constrained Full
recipes now borrow idle queue storage for explicit OTA, retain all 224 normal
queued frames and all 15 held private messages, and store only authenticated
message fields needed for later delivery. Constant initialization also removes
unused ESP-NOW primary workspace from LoRa-only images. No feature was disabled.
Final C3 linked headroom was 146000 bytes against the existing 145952-byte
requirement, which includes a 16384-byte transient margin.

Native coverage includes the board/include-order default matrix, linked-code
packaging and override contracts, real-crypto protocol interoperability,
224/128 queue ownership and wraparound, compact-message ACK/dedup/FIFO/retry
behavior, and ESP-NOW initialization/fragmentation under sanitizers. CI now
builds T1000-E and SX1276 Full plus constrained C3/C6/Tracker Full images.

### CI follow-up

The incoming CI baseline also failed the Tracker and Station G3 Full MQTT RAM
checks. Their ESP-NOW TX queues retained both encoded frames and a complete
packet used only for clearing an unsent duplicate-cache admission. Each slot
now keeps the full encoded frames and an immutable hash/cache-domain token.
All six slots, both fragments, retry paths and diagnostic behavior remain.
The linked Tracker object shrank by 1632 bytes; RAM reserves were unchanged.

| Build | Internal bytes available | Required | Result |
| --- | ---: | ---: | --- |
| Wireless Tracker Full MQTT | 224608 | 223410 | Pass |
| Station G3 r2 Full MQTT, exact identity | 196744 | 195760 | Pass |
| W12 LR2021 Full Companion | 224944 | 169760 | Pass |

Native tests cover ordinary/ACK cache separation, TRACE keys, caller packet
reuse, six-slot overflow, full fragment draining, failed admission retries,
restart/timeout cleanup, and preserving admissions after a send has started.
Stale preference and radio-diagnostics test fixtures were also brought up to
the production APIs, and the hosted documentation links were repaired.

The separate STM32 RAK3x72 USB Companion flash overflow was already present
before this change (772 bytes in both baseline and feature CI). It remains
unresolved; passing the builds above does not mean the entire workflow passes.

LLCC68 still cannot use SF11 at BW250. Its manufacturer modulation limits
exclude LongFast; enabling software cannot add that hardware mode.
