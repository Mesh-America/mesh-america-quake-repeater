<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/espnow_bridge_diagnostics_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# ESP-NOW bridge diagnostics, 22 October 2026

Status: **host tests and both Full repeater builds PASS**. No radio was
flashed or contacted in this work. The reported V4/V4 R8 TFT bridge delivery
failure remains physically unverified; matching saved settings and
`espnow.running on` do not establish peer receipt.

Clean firmware source
[`400878207`](https://github.com/mikecarper/MeshCore/commit/40087820781b189e0136b0ce73928a717752a5c8)
contains the diagnostics. Both canonical builds used the Full profile,
Cascade runtime defaults, USA Cascade radio preset and version
`v1.18.0.1-halo-keymind-cascade-dev-40087820`.
The [safe build receipt](espnow_bridge_diagnostics_2026-10-22.safe.json)
records source, artifact hashes and linked memory measurements. Later
documentation-only changes do not alter these firmware artifacts.

## Investigation and changes

Both V4 variants use the same ESP-NOW bridge implementation. No
display-specific forwarding difference was found. `bridge.source rx` is a
valid choice: it exports LoRa receptions. If both boards directly hear the
same LoRa message, normal mesh duplicate suppression can discard a later
bridged copy. This is a condition to measure, not an established cause of
the reported failure.

Normal builds previously compiled out the bridge's verbose debug path.
Runtime USB logging/debug can now produce bounded ESP-NOW summaries without
a special build flag. Status exposes the configured and actual 2.4 GHz
channel, SDK state, queue depths and historical error stage/code. Separate
counter pages locate RX decode/admission, TX queue/start/completion and
filter/duplicate decisions. No secret is printed.

The local-only `espnow test` command sends a single bounded diagnostic
probe. The peer consumes it before mesh allocation or LoRa forwarding. It
has no echo or retry and does not modify saved settings. The probe checks
2.4 GHz reachability only; it is unauthenticated and does not validate the
wrapped secret or normal packet format. Confirm receipt using the peer's
increased `rx` count and matching `rxid`, then test the other direction.
SDK send success alone is not application receipt; see the
[Espressif ESP-NOW documentation](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/network/esp_now.html).

Use [the diagnostic procedure](../espnow_bridge_setup.md#locate-a-mesh-forwarding-failure)
and [CLI reference](../cli_commands.md#bridge-when-bridge-support-is-compiled-in)
for the counters and exact command grammar. The USB summary requires both
`usb.logging on` and `usb.debug on`; record and restore both original values
after a short capture. Counter pages and probes need neither logging gate.

## Build results

| Canonical target | Selected Full environment | Available internal bytes | Required heap bytes | Result |
| --- | --- | ---: | ---: | --- |
| `heltec_v4_repeater` | `heltec_v4_repeater_observer_mqtt` | 202,576 | 192,656 | PASS |
| `heltec_v4_r8_tft_repeater` | `heltec_v4_r8_tft_repeater_observer_mqtt` | 200,344 | 190,608 | PASS |

The largest linked internal regions are 169,808 and 167,576 bytes respectively,
against a required contiguous allocation of 21,184 bytes. These are linked
capacity estimates, not runtime free-heap, fragmentation or maximum-load
measurements. Application and merged packages, memory gates, OTA packaging
and linked capability verification pass for both targets. Both capability
receipts report the Full profile with no feature reductions.

An initial attempt at source `14682de00` compiled but was rejected by the
immutable-input packaging guard because generation changed the embedded web
page header. That header was committed in `400878207`; both qualifying builds
then passed from clean source. The rejected attempt is retained privately and
is excluded from the safe receipt.

## Verification and limits

The host validation passed for:

- Diagnostic codec and actual bridge runtime: strict input/CRC handling,
  legacy parser rejection, SDK callback variants, queue/pool pressure,
  one-attempt probes, unchanged normal retries, status and bounded output.
- Diagnostic CLI: strict grammar, local-only actions, response bounds and
  bridge selection across role combinations, including sanitizer builds.
- Existing bridge recovery, transport filter wiring, radio lifecycle,
  ESP-NOW runtime and bridge ingress regressions.
- Cooperative ESP32 USB output, USB debug/prefs, hosted documentation links
  and strict documentation rendering.

Callback work remains bounded and does not print or allocate. Counter
snapshots and resets use the existing RX/TX locks. Diagnostics are guarded
by ESP-NOW bridge support, including the CLI callbacks, so unrelated firmware
roles do not acquire the new callback interface.

No physical WiFi coexistence, MQTT coexistence, LoRa delivery, probe exchange
or USB debug capture was performed. Actual pair qualification still requires
the new readings and fresh LoRa traffic in both directions. Stop/restart can
discard pending queue work without classifying delivery; lifetime counters
are not a complete end-to-end delivery ledger.
