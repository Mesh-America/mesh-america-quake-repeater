# ESP32 web console and browser OTA - 2026-10-05

This is a local qualification checkpoint, not a release approval. GitHub writes
and publication of 1.17.1.9 remain on hold. Firmware source for the final runs
is `7821329851f69b6b945f061bc4d15212d43c3198`.

## Coverage gap and reproduced failures

Earlier component and simulated-peripheral tests did not establish the complete
V4 browser flow. In particular, accepting a `Started` reply did not prove that
a normal WiFi client could discover the hotspot or connect to its HTTP server.
The actual embedded uploader also had to receive its completion response before
the radio restarted. Those boundaries needed physical qualification.

The physical V4 runs found three failures:

- ESP-NOW could leave the AP protocol mask at 15, including the proprietary LR
  bit. OTA returned an IP, but an ordinary WiFi client could not discover it.
  Explicitly restoring the AP to b/g/n (mask 7) made it discoverable.
- The old AsyncElegantOTA implementation restarted from its network callback.
  A real browser upload installed the new image but timed out waiting for its
  completion response. The fixed implementation lets the response finish and
  schedules the reboot outside that callback.
- Repeated stop/start could leave port 80 unavailable while CLI still reported
  success. The private, source-pinned AsyncTCP build now allows rebinding past
  completed connections, and OTA verifies that the listener actually started.

Host regressions also cover background ESP-NOW retries undoing an OTA pause,
WebConfig teardown retaining OTA's WiFi, upload ownership and interruption,
failed binds, and complete CRLF replies through the stock web console client.
Negative controls fail with the old AP protocol, TCP binding, callback reboot,
USB sleep guard, or line delimiter behavior.

## Final physical observations

| Check | Result and boundary |
| --- | --- |
| V4 actual browser upload | PASS. Chromium ran the unchanged embedded AsyncElegantOTA page. Multipart upload returned HTTP 200 `OK`; normal reboot loaded a distinct target version. USB answered afterward without another reset or unplug. |
| V4 OTA startup | PASS for WiFi off -> OTA, WebConfig setup AP -> OTA, ESP-NOW coexistence, WebConfig LAN -> OTA, and an active LAN uploader -> OTA AP. The returned URLs served real pages across deferred cleanup. |
| V4 USB idle | PASS for 600 seconds with no transmitted commands or keepalives, power saving on, USB logging on, and DTR asserted. Subsequent query and close/reopen passed; uptime advanced from 111 to 717 seconds. |
| V4 DTR deasserted | PASS for immediate queries, 30 seconds idle, and reopen using an opener that established RTS low before deasserting DTR. No reset or startup delay was added. |
| XIAO S3 WIO Companion | Restored from the temporary Repeater test role using an application-only flash. Partition signature and identity were preserved. All 60 read-only replies met the two-second deadline, including 10 held query pairs and 10 reopen pairs; maximum latency was 22 ms. |

The V4 console runs above use the unchanged official `SerialConsole` through
Node Web Streams and a physical Linux serial transport on Mercerwood. They do
not exercise Chromium's OS Web Serial backend on that remote V4. Earlier
physical XIAO browser tests are separate evidence, not a substitute for it.
The client is pinned to `meshcore-dev/flasher.meshcore.io` revision
`45a5257bf792b11a83f4c51c18d4f312addfb677`, with `lib/console.js` SHA-256
`107d3ad867915aea8b2454c324327397a0f9e2f0469656046054011bc64475f9`.

The first disposable LAN association failed. A separate run with a fresh SSID,
explicit WPA2/RSN CCMP configuration, AP readiness, and credential readback
passed on the same firmware. The first failure is retained; these observations
do not identify which test-network difference caused it.

Two DTR-deasserted first-query runs also failed. Their original pyserial opener
briefly presented the USB hardware reset combination; the boot log recorded
`USB_UART_CHIP_RESET`. Correcting the opener's line-state order passed without
a reset or settle delay. These are retained test-fixture failures, not evidence
that the user's intermittent console hang has been fixed.

During the 600-second idle run, dispatcher flags changed from 0 to 8. The radio
remained in RX with no receive errors, zero received packets, and a configured
five-minute receive-silence watchdog. This is consistent with the existing
radio recovery policy on a quiet channel; uptime proves the MCU did not reboot.
It is not an error-free RF stress qualification.

## Artifacts and host checks

V4 application installed by the successful browser run:

- Version: `v1.17.1.9-hil-ota-upload-78213298`.
- Size: 2,093,336 bytes.
- SHA-256: `ebee70b05528b21aaaeddf8bc80f2762b7ad767ff5b6f29eadf8e2a78e90859d`.

XIAO application restored after console testing:

- Version: `v1.17.1.9-hil-web-ota-78213298`.
- Size: 2,082,584 bytes.
- SHA-256: `605a6b904756ab6d8dcdee8fd9288a996103c59e4f339d7768ece3497c57cfb3`.

Both firmware builds passed. On this source, focused host checks passed:
OTA startup 7, OTA lifecycle 15, async web lifecycle 2, official web console 3,
WebConfig 40, and V4 partition migrator 4. PlatformIO was run serially.

Private raw logs and safe reports are retained under
`/tmp/meshcore-hil-20261004/web-console-investigation`, including the failed
runs. The index `782-evidence-index-safe.json` records evidence hashes.
Temporary V4 settings and the Pi network are restored after testing. The G2,
its recovery ACLs, and its running MQTT services were not changed by this run.

## Remaining limits

The subsequent [current Full V4 native browser qualification](hardware_validation_heltec_v4_native_console_2026-10-06.md)
adds actual Pi Chromium Web Serial, the unchanged setup GUI's five-second
deadline, and measured fresh-flash and power-saving console idle results. The
older source and boundaries above remain historical evidence. Neither report
qualifies every host OS, physical USB adapter, cold power cycle, ESP32 board,
firmware profile, or radio traffic load. USB-attached console checks do not
establish CPU sleep, measured current or button wake. The subsequent V4
button-wake profile correction passed host/build validation and another native
GUI fresh-flash plus 180-second open/closed console check, as recorded in that
linked report. On 2026-10-06 the user separately confirmed V4 button screen wake;
its firmware revision and CPU sleep state were not specified. The operator
USB tests included no actual button press or sleep/current measurement.
