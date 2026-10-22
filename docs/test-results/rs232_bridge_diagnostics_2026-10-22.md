<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/rs232_bridge_diagnostics_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# RS-232 bridge diagnostics, 22 October 2026

Status: **host tests and ESP32 Full build PASS**. The RAK4631 Reduced
sensor/LoRa OTA build passes, but its Full sensor build fails the RAM gate.
The same Full failure occurs on the previous source, before these diagnostics.
The required nRF52 Full/Reduced pair remains incomplete and is not a qualified
release. No radio was flashed or contacted in this work.

The feature implementation is
[`281f1a519`](https://github.com/mikecarper/MeshCore/commit/281f1a519),
with additional host UART platform adapters in
[`df08877c1`](https://github.com/mikecarper/MeshCore/commit/df08877c1).
The ESP32 build used the implementation source with those test-only adapters
already present locally. The nRF52 build used committed `df08877c1`.

## Behavior

The existing `get rs232.status` heartbeat/automatic-standby report remains.
`get rs232.transport` adds UART state, baud, RX/TX pins, packet source,
partial/pending frame state and historical errors. Separate RX, TX, drop and
test counter pages distinguish framing/checksum failures, pool pressure,
blocked/short writes, filters and duplicates. Statistics occupy 120 bytes
inside the bridge object, with no new persistent preferences.

`rs232 test [8 hex digits]` queues a reserved, one-way UART control frame.
The receiver consumes it without allocating a mesh packet, updating duplicate
tracking, establishing heartbeat liveness, replying or forwarding onto LoRa.
Confirm receipt using the other updated board's increased probe `rx` count
and matching `rxid`; local UART write completion does not prove delivery.

Fault testing found that cancelling a partially emitted control frame could
confuse an older receiver's following frame. The implementation cancels an
entirely unsent probe at its deadline, but retains and drains an already-started
frame's original suffix. It never retransmits the prefix or interleaves another
frame. A timeout records one failure; a later local completion can also count
as sent. Each loop's diagnostic work remains bounded.

Both `usb.logging on` and `usb.debug on` enable bounded `RS232:` summaries in
ordinary bridge images, at most once per second when diagnostic state changes.
CLI pages and test probes require neither logging gate. See the
[setup and diagnostic guide](../rs232_bridge_setup.md) for exact commands.

## Embedded build checks

Canonical builds used version `v1.18.0.1-halo-keymind-cascade-dev`, Cascade
runtime defaults and the USA Cascade preset. These were compile/package
checks, with no physical UART, LoRa, USB capture or OTA operation.

| Target/profile | Available internal bytes | Required heap bytes | Result |
| --- | ---: | ---: | --- |
| `Heltec_v3_repeater`, selected Full MQTT/UART/ESP-NOW image | 209,472 | 203,920 | PASS |
| `RAK_4631_repeater`, Full sensors + LoRa OTA | 82,324 | 85,152 | FAIL |
| `RAK_4631_repeater`, Reduced sensors + LoRa OTA | 85,336 | 85,152 | PASS |
| Previous `e7b863494`, same RAK Full recipe | 82,324 | 85,152 | FAIL |

The ESP32 Full image passes its application/merged package and linked
capability checks with no feature reductions. Its largest internal region is
176,704 bytes against a 21,184-byte contiguous requirement. These are linked
capacity estimates, not running free-heap or maximum-load measurements.

The RAK Full shortfall is exactly 2,828 bytes on both sources. No memory guard
or reserve was lowered. The new nRF52 bridge allocation is 2,656 bytes, within
the unchanged 2,816-byte source assertion. Reduced is a separate supported
profile; its pass does not qualify Full or replace the failed required pair.

## Host validation

- Eight diagnostic methods passed across five sanitizer builds: ESP32 ordinary
  and native USB, nRF52, RP2040 and STM32. Cases include invalid control frames,
  both legacy parsers, pool exhaustion, liveness isolation, every partial probe
  prefix, timeout recovery, saturation, reset and bounded runtime logging.
- Three CLI methods passed across seven sanitizer configurations, including
  local-only actions, strict grammar, reply bounds, transport combinations and
  unsupported roles. Existing ESP-NOW CLI checks also passed.
- Bridge-only native USB formatter checks passed on nRF52 and ESP32 with
  compile-time debug flags off. Existing heartbeat, UART lifecycle, independent
  MQTT/UART runtime, power settings/ownership, filter wiring, bridge recovery,
  ingress and ESP-NOW diagnostic regressions passed.
- Allocation-budget boundary checks, hosted links and strict documentation
  rendering passed.

Physical cable/line-driver behavior, actual peer probe receipt, UART sleep
rendezvous, USB debug capture and end-to-end LoRa delivery remain untested
for this change.
