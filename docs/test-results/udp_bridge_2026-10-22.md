<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/udp_bridge_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Eight-peer WiFi UDP bridge, 22 October 2026

Status: **host tests and all three Full repeater builds PASS**. No radio was
flashed or contacted. Physical WiFi/UDP delivery, router policy, LoRa forwarding
and OTA operation remain outside this validation.

Clean firmware source
[`f4a9a05f7`](https://github.com/mikecarper/MeshCore/commit/f4a9a05f7)
was built with the canonical builder, version
`v1.18.0.1-halo-keymind-cascade-dev`, Cascade runtime defaults and the USA
Cascade preset. The [safe receipt](udp_bridge_2026-10-22.safe.json) binds
source, build recipes, linked memory measurements and package hashes.

## Resulting behavior

Supported ESP32 Full repeaters gain a default-off UDP bridge with eight
explicit IPv4/port peer slots. One bounded, nonblocking socket runs only on a
connected station with an IP address and exact station-only SDK mode. It
pauses on disconnection, AP/AP+STA, browser/deferred WiFi OTA and manual WiFi
shutdown, then restores eligible saved intent. It can join using existing
WiFi credentials without an MQTT broker or a running MQTT worker.

Packets use versioned HMAC-SHA256 authentication with the existing
`bridge.secret`; no new password is added. Fresh challenge/proof exchanges
establish boot sessions, with receiver-boot binding and monotonic receive
sequences rejecting replayed mesh packets and probes. Changing the shared secret
closes old sessions and discards old queued work before further socket service.
Authentication does not encrypt the UDP payload.

Local LoRa traffic can fan out to the eight direct destinations. Incoming
UDP enters the local LoRa mesh, with the usual filters and admission rules;
it is not forwarded to other UDP peers. A volatile packet-origin marker
prevents later LoRa TX callbacks, including OTA retries, from exporting that
same UDP ingress packet again. The marker survives retry copies, is never
serialized, and fits existing packet padding. Unrelated builds do not gain it.

The [setup and diagnostic guide](../udp_bridge_setup.md) covers saved settings,
status, counters, one-way probes and runtime USB summaries. `ready` counts
authenticated boot sessions, not current peer liveness. Match a fresh probe's
ID and increased receive count on the destination to establish reachability.
Probes do not allocate mesh packets, echo, retry or reach LoRa. Automatic
handshake controls have their own bounded retry policy.

## Embedded build results

| Requested target | Selected Full environment | Available internal bytes | Required heap bytes | Model margin | Result |
| --- | --- | ---: | ---: | ---: | --- |
| `Heltec_v3_repeater` | `Heltec_v3_repeater_observer_mqtt` | 209,392 | 209,040 | 352 | PASS |
| `heltec_v4_repeater` | `heltec_v4_repeater_observer_mqtt` | 202,496 | 197,776 | 4,720 | PASS |
| `heltec_v4_r8_tft_repeater` | `heltec_v4_r8_tft_repeater_observer_mqtt` | 200,264 | 195,728 | 4,536 | PASS |

Each image passes application and merged packaging, linked capability checks
including `bridge.udp`, and unchanged memory/size gates. All capability
receipts have empty feature-reduction lists. No feature or reserve was removed.

The enabled-case model adds 5,120 bytes even though UDP defaults off: a source-
asserted 3,072-byte object allowance and 2,048 bytes for the bounded socket and
receive buffering. The socket requires a successful 768-byte receive-limit
configuration. WiFi stack memory is counted once alongside MQTT, with UART
and other existing allocations still reserved. The V3 model margin is small;
these linked capacity estimates are not running free-heap, fragmentation or
maximum-load measurements. Physical startup/load/soak checks remain necessary.

An initial compile attempt at `5e25faa3d` exposed aggregate initialization
unsupported by the pinned ESP32 compiler. `f4a9a05f7` uses explicit field
assignment. The host suite now compiles the production UDP implementation
with strict C++11 before linking its test driver. The earlier failure is
retained privately and excluded from qualifying packages.

## Host checks

- Eight sanitized core methods in both native-USB and ordinary-console builds:
  strict framing and a Python HMAC known-answer vector, mutations/oversize,
  old-session and reboot replay rejection, simultaneous eight-peer startup,
  fan-out, targeted probes, key rotation, pool/backpressure, socket errors,
  network changes and bounded logging.
- Three config/OTA methods: strict CLI and local-only test/reset, checked
  standalone settings, write faults/power interruption, unchanged common
  preferences, and correct pause/restore including manually paused UDP.
- Two integration methods across owner combinations: exact STA versus AP and
  stale SDK state, reconnect, manual-off grace, MQTT independence, foreground
  power ownership, setup/OTA transitions and failed settings saves.
- Production packet/pool/dispatcher checks: nonserialized origin, retry-copy
  preservation, reuse/parser reset and unchanged packet size. Bridge-only USB
  formatter checks include a UDP-only build with compile-time debug off.
- Build-profile, allocation-boundary, existing network/wireless/power/RAM,
  bridge recovery/filter/ingress, MQTT/UART and USB preference regressions.
- Hosted documentation links and strict documentation rendering.

Router client isolation cannot be diagnosed conclusively from a successful
WiFi association alone. The physical network must allow the configured peers
to exchange UDP. This work did not change router settings or attempt to bypass
network isolation.
