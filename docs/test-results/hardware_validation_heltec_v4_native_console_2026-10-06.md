<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_heltec_v4_native_console_2026-10-06/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Heltec V4 Full native browser console - 2026-10-06

The normal Full Heltec V4 Repeater from source
`c88885a315208908e050c57fc0ec0a71ff10bd6f` passed fresh-flash connection,
600 seconds with the console open, and 600 seconds with it closed through the
unchanged `config.meshcore.io` setup GUI. Power saving was on and logging output
was off during those idle intervals. A separate fresh-flash and 600-second
open-console trial also passed with USB logging on. Both trials restored the
original settings and closed their streams. Final operator readback and owned
browser/host-service cleanup also passed. Release 1.17.1.9 remains held and
unpublished.

The subsequent button-profile correction at `ebf2f082` passed host/build checks
and another native fresh-flash GUI connection with 180-second open/closed
console intervals. That updated-source checkpoint is recorded separately below;
it does not extend the older source's 600-second measurements to the new image.

On 2026-10-06, the user separately confirmed that a Heltec V4 button press wakes
the screen. This is a user-reported manual confirmation; its firmware revision
and CPU sleep state were not specified. It does not supply a current measurement
or a V4-R8 manual result.

These results extend the [earlier startup investigation](hardware_validation_esp32_web_console_startup_2026-10-05.md)
to the current normal Full image and native hardware CDC. They are physical
console stability checks, not a measurement of sleep current, radio traffic
capacity, or every ESP32/host combination.

## Image and build gates

The requested target was `heltec_v4_repeater`, Full profile. Its resolved
`heltec_v4_repeater_observer_mqtt` feature base retains the normal repeater
update identity. Runtime readback had to match the complete version
`v1.17.1.9-halo-keymind-cascade-dev-c88885a3 (Build: 06-Oct-2026)`.
The source includes the OTA upload correction in `d2983762` and WiFi ownership
correction in `95913c53`. The GitHub unit workflow for `c88885a3` passed;
this does not replace the physical checks below or the final release matrix.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Full application | 2,097,528 | `1f10f44149b3f56edbe0ecb2a2bab9b51da651a6d047e2c2c1555691468d2b4c` |
| Merged image | 2,163,064 | `3264d7a1a5713755b5dd10ad1c81bb0588e4a072eeaa126b86307a42be77bb5b` |
| Matching ELF | - | `0545eef46da30a86f86531199a91e887167d463c5981f193c0455cd75d633538` |

The package hash, linked capability, and RAM gates passed, with 20,880 bytes
of margin above the required heap budget. The linked application includes
HWCDC, its retained-PHY handoff and startup owner hook; no TinyUSB USBCDC class
is linked. Full ESP-NOW, WiFi/LoRa OTA, and USB logging capability checks passed.
These are build checks; this run did not exercise those radio/OTA features.

Both application slots are `0x640000` bytes, at `0x10000` and `0x650000`.
The padded partition table SHA-256 is
`9af3af2b74e944337ba85f2b0027ee80df160579a1ab746ba0f95853f618cd60`.
The merged image contains that table and the exact audited application at
`0x10000`. The application fits either slot with 4,456,072 bytes of margin.
The merged artifact was audited, but the physical tests wrote the application
only; they do not qualify a factory erase or merged-image installation.

## Native browser boundary

Chromium `154.0.8037.92` ran on the Pi with native OS Web Serial ports and
streams. The actual Vue GUI and stock SerialCLI were loaded before flashing.
The stock DOM Connect flow after the stock flasher returned sent the normal
plain `time <epoch>` request. Its unchanged 5,000 ms timeout covers both native
write completion and the framed response. No additional reset, cable action,
post-flash settle, command retry, or keepalive was inserted to turn that
connection into a pass.

| Website source | SHA-256 |
| --- | --- |
| GUI `index.html` | `efd64d1b56d57988fc4108f3f84efc943ed4c42ade4e4dbf8139c46fb3c0476d` |
| GUI `src/gui.js` | `919034806e903fbc41e29a367a7d854837f6520f47aa34e5d0618f5dd3d29800` |
| GUI `lib/serial-cli.js` | `fbfbdcfa8bf1a372a0396d342e018ba8ee83d33b7b98c3a546fd37cd7e8ce870` |
| Flasher `js/flash.js` | `e9762a29f6a91f8e33736e02ff41a81cd49e7b96fe253a5d71cba7daefd46d5b` |
| Flasher `lib/esp32.js` | `2a896d5e520ea9b6ea9900223c2460df797c3b2287f441daa4e50168a50b17e6` |

Automation selected only the single preauthorized native device. Before each
write, actual ROM reads checked the partition table and valid OTA sequence/CRC,
then directed the application write to the verified active slot (`app1` at
`0x650000`). The stock loader transfer, reset and disconnect remained in place;
full erase was disabled. Phase instrumentation recorded existing calls without
adding hardware operations. This qualifies that stock flash backend and native
GUI connection, not the complete firmware-picker selection/erase flow.

Original public identity, the ACL response, and 15 checked saved preferences
were compared with the original private reference after flashing and cleanup.
Only the numeric channel-busy diagnostic counter was normalized in preference
comparison. No raw identities, credentials or console replies are published.

## Physical results

| Check | Result |
| --- | --- |
| Fresh flash, then first GUI connection with logging off | PASS. Plain time clock-set acknowledgement in 1,614.4 ms; complete GUI bootstrap and exact version/reference checks passed. |
| Power saving on, logging off, console open | PASS. 600.093 seconds with zero native command writes or keepalives. Uptime advanced 18 -> 619 seconds; the first post-idle core reply took 35.9 ms. A full DOM Disconnect/Connect reread acknowledged time in 23.6 ms. |
| Power saving on, logging off, console closed | PASS. 600.100 seconds with streams closed and zero writes. Uptime advanced 627 -> 1232 seconds. The first DOM reconnect time response took 33.2 ms; it was the recognized framed clock-cannot-go-backwards rejection, not a clock-set acknowledgement. Full GUI bootstrap and version checks still passed. |
| Separate fresh flash, power saving on, USB logging | PASS. Fresh plain time acknowledgement in 696.1 ms, then 600.101 seconds open with zero writes or keepalives. Uptime advanced 18 -> 618 seconds; first post-idle core reply took 40.4 ms. Full DOM reconnect time acknowledgement took 24.8 ms. |
| Both trial cleanups | PASS. Original power saving off, logging output USB, all 15 checked preferences, public identity and ACL response were restored. The GUI port, reader and writer closed. |

Uptime gates account for the surrounding query/GUI bootstrap time. None of the
three quiet intervals contains a native write event. Both trials recorded zero
native command errors and no GUI modem-signal calls.

Radio observations stayed in active RX with zero physical RX errors. The core
error bitmask changed from `0` to `8`, with zero received packets and one sent
packet. This is the configured receive-silence watchdog warning, consistent
with the quiet-channel recovery policy; it is not eight errors or a CPU reset.
Neither trial establishes error-free RF operation or a loaded radio soak.

## Retained setup failures and host qualification

Two preceding browser attempts remain failed and unqualified. Attempt 2 timed
out before metadata completion or any GUI command was recorded; its exact
flasher substage was not instrumented. Attempt 4 timed out in the stock loader
connection/reset loop after 674 USB JTAG reset entries. It did not reach loader
main return, application `writeFlash`, or a GUI command. Neither failure
exercised the GUI's five-second command timer, so they are not counted as
firmware console timeout failures or silently converted into passing trials.

Before the passing logging-off attempt, the host TTY was normalized from
`VMIN=0, VTIME=0` to `VMIN=1, VTIME=0`, with zero explicit modem-signal calls
in that preparation. No firmware or website code changed. That host setup is
part of the qualified configuration; the evidence does not isolate the original
ROM synchronization failure's cause. The second logging trial started without
another external CLI preflight or TTY change.

The pinned stock flasher also calls `connect(resetMode, romBaudrate)` from
`detectChip`, although the second `connect` argument is a retry count with a
default of seven. The supplied value is 115,200. This explains the excessive
retry budget after failed synchronization, not why synchronization first failed.
It is an external flasher issue; no website patch was required for the passing
GUI tests and no website deployment is claimed.

## Evidence and limits

Final read-only operator verification again matched the exact version, original
15 checked preferences, public identity and ACL response; uptime was 686 seconds
and flags remained `8`. The owned Chromium profile and tunnel were closed, the
serial port had no owner, and original host service states were restored:
ModemManager and mctomqtt active, mesh-logger inactive. No Pi network
configuration changed. Restored service state does not establish MQTT delivery.

The compact [safe audit](hardware_validation_heltec_v4_native_console_2026-10-06.safe.json)
contains artifact/helper/report hashes and selected outcome fields. Completed
sanitized reports and phase observations are retained privately; raw reference
settings remain private. Failed attempts are retained separately from the
qualified results.

The USB cable remained attached throughout these trials. The native-host sleep
guard keeps CPU command service available while the USB host is connected,
including when its serial port is closed. Power saving on is therefore not
proof of CPU light-sleep entry, measured current, or an operator button test.
At this source, V4 lacks the momentary-button wake profile flag. Its subsequent
software/build and console validation is recorded below. The operator had no
physical button access in this setup. The user's separate screen-wake
confirmation does not establish this historical image's CPU sleep state.

These checks qualify this historical `c88885a3` Full application, native Pi Chromium setup,
protected active-slot application flash, and measured intervals. They do not
qualify every host OS, board/role, adapter, cold power cycle, factory erase,
heavy logging volume, measured power consumption, or RF traffic load. GPIO/reset
behavior outside the unchanged stock flasher's reset sequence was not separately
qualified. The release remains unpublished; the final same-source all-board
build and release packaging are separate gates.

## Updated button-profile checkpoint: `ebf2f082`

Source `ebf2f0823ef8413987d31ccb2d044a2090e88469` enables the existing
momentary-button wake flag in the shared V4 and V4-R8 profiles. Seven ESP32
USB/sleep tests and two display-power tests passed. Configuration assertions
cover 71 firmware profiles, excluding four deliberately standalone partition
migrators. Six host cases execute actual board sleep/USB methods, real family
button constructors and implementation, role polling guards, UITask button
fragments and DisplayPowerPolicy. Three controls must fail if the profile flag,
gesture polling guard or display wake is removed. These are synthetic GPIO/sleep
results, not a physical button press.

| Updated artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Full application | 2,097,560 | `aebfd06f5e35ad636f52f329bd051deb9dfeb633361dc77396c0ee9d4456e7c1` |
| Merged image | 2,163,096 | `08750bd38f9f71ea37b8739a8b3c26befa91829df6d5754ad9cffbf61a796a90` |
| Matching ELF | - | `c2ec6d54c32c4b3cb331f9216607480e851933cf4865cc399be9409fdf587467` |

The normal Full target, table, two slots, capabilities and RAM gates passed,
with the same 20,880-byte required-heap margin. Linked instructions now contain
the GPIO0 pending-press check, active-low wake and button cleanup, plus the
gesture polling guard, while retaining radio IRQ14 wake. The HWCDC PHY handoff
and startup hook remain linked; no TinyUSB USBCDC class is linked. This confirms
the profile flag reached the application rather than only its source recipe.

The same pinned stock native GUI/flasher and unchanged 5,000 ms deadline were
used. Before this flash, host-only TTY preparation again changed VMIN/VTIME from
0/0 to 1/0 with zero explicit modem-signal calls. The app-only ROM preflight
again selected the protected active slot. Exact runtime readback was
`v1.17.1.9-halo-keymind-cascade-dev-ebf2f082 (Build: 06-Oct-2026)`.

| Updated-source check | Result |
| --- | --- |
| First stock DOM GUI Connect after fresh flash | PASS. Plain time clock-set acknowledgement in 2,036.4 ms; full GUI bootstrap, exact version and original reference checks passed. No extra reset, replug, settle or retry. |
| Power saving on, USB logging, console open | PASS. 180.061 seconds with zero native writes or keepalives; uptime 17 -> 198 seconds. First post-idle core reply took 39.7 ms; full DOM reconnect time acknowledgement took 45.0 ms. |
| Power saving on, USB logging, console closed | PASS. 180.100 seconds with streams closed and zero writes; uptime 205 -> 391 seconds. First DOM reconnect time response took 26.7 ms and was the recognized clock-cannot-go-backwards rejection, not an acknowledgement. Full GUI bootstrap passed. |
| Cleanup and operator readback | PASS. Original power saving off, USB logging, all 15 checked preferences, public identity and ACL response were restored. Streams closed; independent operator readback again matched the exact updated version and original digests at uptime 448 seconds. |

There were no native command errors or GUI modem-signal calls. Radio remained
in active RX with zero physical RX errors; flags changed 0 -> 8, received
packets stayed zero and one packet was sent. This remains a receive-silence
watchdog warning, not a CPU crash or loaded-radio qualification. The owned
browser and tunnel were closed, the serial port had no owner, original host
service states were restored, and no Pi network configuration changed.

The compact safe audit records this as `updated_source_checkpoint`, separate
from the older 600-second trials. The updated source qualifies these
180-second console intervals. The operator did not physically press the button;
the user's manual screen-wake confirmation is recorded above without assigning
it a firmware SHA or CPU sleep state. CPU sleep and current draw were not
measured in these USB-attached tests. GitHub unit run `37426156162` for this new
source is still in progress at this checkpoint. Release 1.17.1.9 remains held
and unpublished.
