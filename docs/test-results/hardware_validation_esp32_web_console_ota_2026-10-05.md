<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_esp32_web_console_ota_2026-10-05/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

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


## Release candidate follow-up recorded 2026-10-07

The following source-scoped observations were originally recorded in the
1.17.1.9 candidate release notes. They are retained here as historical test
results, including failed attempts and their separate recoveries. Build and
publication status in this snapshot does not override the final
[release notes](../releases/1.17.1.9.md#verification-scope). Older passing
images do not qualify a later firmware revision or turn an earlier failure
into a pass. Latest-source V4 hardware was unavailable for a repeat; that is
a physical coverage limitation, not a failed latest-source test.


The [earlier c5 GitHub unit workflow](https://github.com/mikecarper/MeshCore/actions/runs/37550980479)
passed all four jobs. Host regressions exercise production OTA callbacks,
the official configuration GUI and app protocol behavior, including MD5
ordering, rejected second files, incomplete POSTs, cleanup and subsequent
valid uploads. Sanitizer fixtures cover these OTA lifecycle cases. These
checks use MeshCore's actual-code fixtures; MeshBench is not integrated.

For `1e421ff4`, the coupled production WebConfig credential interception,
NVS commit, CLI routing and MQTT consumer fixture passed four tests, including
fresh portal-only setup, legacy fallback, reconnects, raw-PSK boundaries,
failed and interrupted writes, and mutations that restore the old credential
lookup. The broader WiFi and MQTT host suites passed 62 and 14 cases,
respectively, with some overlap. The WebConfig host suite passed 53 cases,
including the embedded page in an isolated Chromium headless browser.
Seven infrastructure power-lifecycle cases
and six portal-ownership cases passed. Five V4 setup-page cases include actual
button/session handling under both signed and unsigned `char`. The new tests
are explicitly included in the unit workflow. The [current GitHub unit workflow](https://github.com/mikecarper/MeshCore/actions/runs/37570287426)
at documentation and host-test commit `4c5f58f4` passed all four jobs; its
firmware source remains `1e421ff4`. The completed local release passed the
strict package checks below; V4 OTA and G2/V4 portal-to-MQTT hardware checks
remain pending.

The completed local all-board release has 463 qualified recipes and 926
firmware files. Its complete checksum inventory, capability and memory
checks passed independent read-only revalidation. All 94 exact ESP32
board/role migration ZIPs and their combined archive passed validation.
The 114 nRF52 infrastructure targets each have a qualified Full/Reduced
pair with matching actual DFU identity, firmware and flash layout. These
results qualify local packages from `1e421ff4`; they do not qualify the
pending physical upgrade paths or publish the release. The newer
`bd4cbf281` source protects ordinary setup/OTA APs from the SDK's shared
long-range WiFi flag, defers conflicting ESP-NOW starts and keeps long-range
protocol writes out of saved WiFi settings. It reports an active ESP-NOW
conflict before starting an AP. The subsequent `8c4e09275` source also defers
MQTT station maintenance and Full Companion station recovery while an AP
owns WiFi. Final builds and hardware qualification of this candidate remain
pending. Final public assets and catalogs still require their separate
inventory and digest checks.

The physical G2 and V4 tests used the unchanged embedded browser uploader
and the normal host console, retaining the stock 5-second first-command
deadline. The earlier `c5fe8a0e` applications passed AP uploads with HTTP
200/OK, automatic restart, and preserved identities, ACLs and saved settings.
The G2's initial upload completed in 19.053 seconds; the V4's completed in
16.392 seconds. First ordinary replies took 1.385 and 1.010 seconds,
respectively, without a cable replug or reset rescue.

On the G2, a full valid first file followed by a second file returned HTTP
409 without an observed MCU restart. A full-file request with an incomplete
closing multipart boundary also left uptime continuous. A valid upload then
passed through that same running listener in 18.767 seconds. Full-image
wrong-MD5 requests had already returned HTTP 400 without restart on parent
`70bf4bdf`. The tests do not claim that rejected requests leave the inactive
flash slot untouched. A fresh 385-second sample of unmodified Cisien
meshcoretomqtt had all four brokers connected, zero publish failures and no
service restarts; both the original and recovery Admin ACLs were preserved.
The earlier G2 LAN upload stall is treated as a local slow-WiFi limitation,
not a release blocker. LAN upload was not qualified by these AP tests.

The new `1e421ff4` G2 Full Observer application also passed the unchanged
native AP uploader: HTTP 200/OK in 18.437 seconds, firmware-owned restart,
and first ordinary `ver` reply in 1.304 seconds. Live EndF body identity,
the exact G2 target and source were verified, with the original 15 settings,
both Admin ACLs, services and the Pi's exact SlowFi connection preserved.
This qualifies that AP update, not fresh WebConfig provisioning into the
on-device MQTT consumer; that check and the new-source V4 checks remain pending.

On parent `70bf4bdf`, both G2 and V4 passed four 600-second quiet intervals:
port open and closed with logging off, then open and closed with USB logging,
all with power saving enabled. Uptime remained continuous, with no host
keepalive writes during the intervals. The V4 reported radio-watchdog event
bit 8; this was not an MCU reset or an all-zero-error result. Its USB-logging
open interval received 26 bytes. The V4 also passed the first unchanged
native setup-GUI connection immediately after a fresh flash, with the first
clock reply in 73.3 ms. These quiet and fresh-flash checks were not repeated
on `c5fe8a0e`, whose change was confined to OTA completion behavior. The
newer canonical-WiFi source `1e421ff4` has the narrower G2 results below.

On `1e421ff4`, the G2 passed one 600.022-second open-port quiet interval
with USB logging and power saving enabled, with no host writes and continuous
uptime. The following 600-second closed-port interval ended in a stock-browser
reopen failure at the test helper's 5-second acquisition gate, before `ver`
was sent. The host then had VMIN=1/VTIME=0; the ordinary exclusive serial
client still replied in 21 ms, with continuous uptime and unchanged core error
flags. This is an unresolved browser/native-port acquisition result, not a
qualified closed-port pass or evidence of an MCU crash. A cleanup-overlay bug
in that test helper was also found and fixed for the instrumented repeat;
the earlier failed receipt is retained.

The instrumented G2 repeat on the same `1e421ff4` source passed both
600-second open and closed quiet intervals with USB logging and power saving
enabled, continuous uptime and no host keepalive writes. Original settings and
the host were restored. The maximum stock Enter-to-reply time was 3.584 seconds.
The second native port open took 5.532 seconds; click-to-connected took
8.201 seconds. That acquisition time is separate from the unchanged 5-second
command deadline, and the helper's connected wait started after its click RPC
returned. This repeat does not reclassify the earlier failure or establish its
cause. The separate logging-off run also passed both 600-second open and
closed quiet intervals with power saving enabled, 85 successful queries,
continuous uptime and restored original settings. Together the completed
runs qualify all four quiet intervals on this G2 and source.

The subsequent 100-cycle acceptance attempt stopped after 32 completed cycles.
All 86 stock commands passed, with a maximum Enter-to-reply time of 450 ms
and no observed MCU reset. The failure was an automation timeout while
clicking the stock close-overlay button; this is separate from the stock
command deadline. At the failed-trial snapshot, the UI had marked itself
disconnected while native close had not started. Native close subsequently
fulfilled in 105.5 ms, and the serial port and page closed. The cause of the
earlier disconnect or click delay remains unproven. The failed receipt is
retained; 100-cycle qualification and follow-up diagnosis remain pending.

A separate Linux Chromium 139 comparison isolated an inherited host TTY
setting: VMIN=0/VTIME=0 produced device-lost stream termination, while changing
only VMIN to 1 gave a stock `ver` reply in 154.1 ms without reset or replug.
That finding does not establish the cause of the later reopen failure above.
See the [Linux Web Serial report](../research/linux_chromium_web_serial_tty.md)
for primary browser-source evidence and the bounded host preflight.

The physical RAK3401 Companion on `70bf4bdf` passed 21 malformed-request
cases with 217 request/reply frames. Its Full Repeater passed the official
native setup GUI and 600-second open/closed quiet intervals with power saving
on, continuous uptime and zero core error flags. It was returned to the
then-current `c5fe8a0e` Full Companion; the first stock SDK reply took 25.9 ms
without an initial retry or settling delay. Original identity, contacts,
channels, custom variables, RX power-saving settings and actual packet-stream
mode were restored. The planned reboot needed to restore stream mode was
separate from the stability measurements. An initial SWD programming failure
was recovered and verified; this was not a first-attempt programming pass.
These tests did not qualify RAK3401 BLE DFU, LoRa OTA or bootloader updates.

The actual published `9053038f` 1.17.1.8 Full V4 installed newer applications
over both AP and a controlled shared WiFi LAN, but its old page did not
receive HTTP completion. Check `ver` before retrying a stalled old page.
These trials used already expanded application slots; actual phone-hotspot
uploads remain untested. The requested legacy small-slot G2 trial now has a
verified existing 16 MiB backup and genuinely programmed and verified the
official 1.14.1 stock components and small-slot table while preserving NVS.
Its first stock USB `ver` request reached the five-second host command limit;
a later read-only probe replied without reset. A separately recorded stock
setup restored and verified the original identity, 22 common settings and two
Admin ACLs after normal reboots. Password setters were confirmed and the guest
password persisted; stock has no admin-password getter. The final `start ota`
returned its expected URL, but the test's AP scan timed out. A subsequent
completed native scan found no `MeshCore-OTA` AP at any BSSID. A later
read-only NVS audit identified the test starting-state problem: earlier
preconditioning had saved the WiFi long-range protocol flag, which stock
inherited. Its long-range AP beacons cannot be received by the ordinary
WiFi clients used here. This does not establish a stock AP startup bug.
A separately recorded correction changed only the fresh live NVS protocol
flag and its entry CRC, with exact readback and unchanged stock components
and small-slot table. After stock identity, common settings, ACL and guest/
private-identity checks, a completed fresh scan found the exact G2 OTA AP.
This establishes the genuine stock WiFi-only starting boundary. The earlier
failed receipts remain failed. The first native migration controller then
failed on a missing host `iw` executable before any HTTP or image-upload
step. It may already have associated with the AP; that outcome was not
verified. Its return to SlowFi and owned guard cleanup passed. A separately
reviewed retry retained the firmware/controller inputs, separately pinned
the old runtime log and checked host executables before using fresh guards.
It associated with the exact stock AP and observed one native bridge-image
POST with the exact bytes, SHA256 and MD5, but the old embedded page did not
complete its HTTP response before the uploader deadline. Browser closure,
return to SlowFi and guard cleanup passed; that transaction remains failed.
A later scan found the exact migration AP. A separately recorded stage2
continuation then verified the actual expanded-layout-ready page and uploaded
the exact `1e421ff4` ordinary Full application through the unchanged native
page, with matching MD5 and HTTP 200/OK in 14.526 seconds. That upload phase
also passed its network return and guard cleanup. The subsequent controlled
Pi AP phase failed on a host `FileNotFoundError` before any final HTTP request.
The host's scheduled WiFi refresh also interrupted that AP phase. Its later
guard-file cleanup refused an unproven network state; a separate read-only
qualification and owned-file cleanup then verified the original network,
dead controller and removal of all prior guard profiles and files. A new
proof-only attempt stopped before AP activation because reloading services
moved the host hold timer's relative deadline. Its failed receipt is retained,
and the held host script was restored. The next proof used a fixed absolute
hold deadline, but stopped before AP activation when a host-file permission
check rejected the actual private service file; its failed receipt and host
restoration are preserved. A third proof verified and ran the isolated Pi
AP with the independent return timer armed, then reached the five-minute
client/DHCP discovery deadline without a verified G2 client or any HTTP
request. It returned to SlowFi, removed its owned network resources and
restored the host's scheduled WiFi recovery script. Final
running-image/layout/identity/settings HTTP verification remains unproven;
the successful firmware upload does not establish that final verification.
After that completed failed WiFi check, separate USB maintenance installed
the `8c4e09275` ordinary Full Observer application. Full application
readback and the normal running version matched, while the bootloader,
partition table, NVS, OTA selection and checked filesystem region stayed
unchanged. This maintenance does not qualify the WiFi-only upgrade. The
saved-settings check found RX boosted gain off instead of its original on;
the other 21 common settings, identity, passwords and two Admin ACLs matched.
A separate checked CLI repair restored gain on and verified all 22 settings.
The first extras restoration then missed the five-second CLI deadline while
changing bridge source. A later read-only probe found continuous uptime,
zero core error flags and the requested source value; it does not establish
the missing command acknowledgment or its save duration. After checking that
state, a separate restoration completed with the original WiFi pair, saved
extras, all 22 common settings, identity, passwords and both Admin ACLs
verified. The MQTT worker was running with valid effective configuration;
broker connectivity was not tested. Original TTY settings, all three host
services and SlowFi were restored, and the exact temporary host executable
alias was removed. The earlier timeout and WiFi proof failure remain recorded.
The loader correction is included in `88c851080`. Its G2 ordinary Full Observer
application was independently read back in full after installation, and normal
boot matched the exact new runtime and EndF footer. The checked lower 64 KiB,
OTA selection and first 64 KiB of the filesystem stayed unchanged. A separate
read-only post-boot check verified the original identity, passwords, two Admin
ACLs, all 22 common settings, seven supported bridge fields and saved extras.
Core error flags were zero; the MQTT worker was running with valid configuration,
without a broker-connectivity claim. Original TTY settings, all three host
services and SlowFi were restored. This USB maintenance does not qualify the
failed WiFi-only final verification. The fresh all-board build and V4 hardware
checks remain pending.
These are separate
outcomes; the initial failed transactions remain failed. The earlier c5
AP upload success does not turn those old HTTP-completion failures into
passes. The [upgrade guide](../upgrading_1.17.1.8_to_1.17.1.9.md) keeps the
old and new updater behavior separate.

Original host services, temporary network changes and owned test resources
were restored after the historical completed hardware checks. The current
new-source V4 native AP OTA trial has not yet produced a verified result;
its return to SlowFi and original host-service state also remain unverified.
The legacy G2 check established the stock starting boundary with its original
identity, common settings and ACLs verified, then completed the expansion and
Full application upload over WiFi. It has not yet qualified the final running
image through HTTP. Post-verdict `88c851080` G2 firmware readback, normal boot,
original-settings acceptance and host restoration passed separately over USB.
The all-board build and current V4 hardware qualification remain pending. These
checks keep publication pending. Build qualification does not
establish physical compatibility on every board. Quiet USB trials do not
measure MCU sleep/current draw, stack high-water, sustained log backpressure
or long-term fleet reliability. Linux native-browser tests required host TTY
preparation; they do not qualify every browser or operating system. Hardware
CDC has finite buffers, and closing a Linux TTY does not necessarily produce
a hardware session reset. See the historical [V4 console report](../test-results/hardware_validation_heltec_v4_native_console_2026-10-06.md)
and [USB backpressure results](../test-results/usb_serial_backpressure.md)
for their exact source revisions and measured scope.
