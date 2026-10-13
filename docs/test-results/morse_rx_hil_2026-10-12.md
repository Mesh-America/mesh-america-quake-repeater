<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/morse_rx_hil_2026-10-12/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Morse receive hardware checkpoint - 12 October 2026

Status: **incomplete hardware validation**. The release default remains
25 WPM / 902.100 MHz and the public limit remains 60 WPM. Experimental
255-WPM builds are not a validated release limit.

## Implementation and host verification

- Companion, repeater, room and sensor command paths support bounded receive
  sessions, a volatile 4096-character capture, paged reads and checked LoRa
  recovery. Receive duration is one second through five minutes.
- Remote receive starts only after its acknowledgement has actually transmitted.
- Fresh focused Morse run: 56/56 passed. Additional high-speed HIL OFF-debounce
  tests and decoder matrix: 3/3 passed, including 188 synthetic waveform cases.
- Radio/role regression run: 390/390. RS232 overlap: 19/19. USB/BLE/logging:
  222 test methods with no functional failures; eight optional DFU emulation
  subcases skipped because the host lacks Unicorn.
- Build checks passed for the tested nRF52 companions/repeater, ESP32 room and
  sensor, and compact STM32 builds. Compact STM32 retains TX but excludes RX
  by default to respect its existing flash boundary.

## Hardware identities and isolation

The Mercerwood Pi was reached at `100.78.195.38`. Only identity-verified
application DFU packages were written through the existing `mcfirmware.sh`
path. No bootloader or SoftDevice was replaced, no services were stopped,
and the Pi was not rebooted by this test.

| Board | USB chip serial |
| --- | --- |
| RAK4631 | `9AB3B64C641BA927` |
| Heltec T096 | `651F8E496197F882` |
| Heltec MeshPocket | `93DA83ADF7B2092B` |

The RAK3401 service radio and MeshTower were left alone.

Early tests put CW at 909.5 MHz and packet profiles elsewhere. This was
corrected: the requested CW default is **902.100 MHz**, separate from the
LoRa lab control tuple **909.5 MHz / 500 kHz / SF5 / CR5**. Results from the
early layout are not proof of packet-spectrum isolation.

`set radio` only saves Companion primary settings. The test runners now use
`set tempradio` and poll the exact active tuple; saved or pending settings
do not satisfy the check. The USB-only HIL recipes explicitly include the
existing temporary-radio capability. Names and saved primary settings are
not changed by the corrected runners.

## Observations, not a new maximum

- With experimental warm-XOSC TX, 800-us PA ramp, RSSI window 2 and 1-ms
  polling, MeshPocket-to-RAK decoded the alphabet/digit, word-spacing and
  punctuation messages correctly in one 120-WPM sweep at 902.100 MHz.
- Reverse-direction captures contained additional noise characters. At
  200/240 WPM, there were real character errors in both directions. Strict
  comparison includes extra characters; matching only a substring is not
  accepted.
- Keeping ordinary FSK packet preamble/sync/CRC did not establish a reliable
  faster limit. That experiment is not enabled in production.
- A no-transmitter control can produce extra characters; the source of those
  RSSI excursions is not established. Noise, another carrier and a radio
  measurement artifact must not be conflated without further evidence.
- Sample-gap diagnostics confirmed mostly 1/2-ms cadence after noncritical
  sensor, display and filesystem work was deferred during capture. The
  protection of voltage cutoffs, GPIO expiry, watchdogs, transport input and
  stop commands remains active.
- Integer-millisecond timing maps 219-255 WPM to the same nominal five-ms dot.
  SPI/PA overhead further slows the envelope. USB-observed TX duration is
  not a precision measurement of physical on-air WPM.

## Remote acknowledgement and retained-capture evidence

A 30-second LoRa-controlled test physically demonstrated:

1. A six-minute request was rejected in 0.682 seconds.
2. The valid request was acknowledged in 0.684 seconds before RX started.
3. The timed receiver returned to LoRa after 30.889 seconds as observed by
   the host.
4. All 34 retained characters read locally were returned byte-for-byte in
   the remote LoRa read.

The decoded RF text was not equal to the transmitted message, so this run
failed overall. It used the early shared CW/control frequency and is not a
clean decoder validation. The full five-minute and multiple-page remote
tests remain outstanding.

## Why hardware work stopped

At approximately 22:43 Pacific the RAK USB connection disappeared during the
zero-gate isolated-frequency sweep. It subsequently reported
`v1.17.1.10-halo-keymind-cascade-preview3-9ce2a076`, with `get morse` unknown,
instead of the just-verified Morse application. Another concurrent job had
flashed the shared RAK. This is not evidence of a Morse firmware crash.
The affected sweep is incomplete and must not be counted as a completed
speed test. Hardware writes were stopped for user coordination.

## Ready-to-resume experiment

An isolated HIL-only `MESH_MORSE_HIL_FAST_OFF_DEBOUNCE=1` experiment keeps
ON confirmation at two ms and permits OFF confirmation at one ms for fast
nominal dots. Default/production behavior, capture size and low-speed timing
are unchanged. Synthetic tests pass; physical results are still pending.

The following application-only packages were compiled and staged on the Pi
but **not installed**:

| Package | SHA-256 |
| --- | --- |
| `RAK_4631_companion_radio_usb-morse-fastoff.zip` | `0340b6135c36c7d6cb61be45ac28555ead5a2f6529feb3702466b284d2abd204` |
| `Mesh_pocket_companion_radio_usb-morse-fastoff.zip` | `e0d94389310244655136564a1dbd55d5e4d4d18a17bbae6e1c7ae018f5bc7952` |

Pi run directory: `/home/mikec/hwtest/runs/morse-20261012.3Lp6jA`.
Local raw evidence is retained in the ignored `out/morse-rx/` directory;
the strict test runners are in `tools/hil/morse_bench.py` and
`tools/hil/morse_remote.py`.

Before resuming, coordinate exclusive use of those three radios, verify the
installed images and exact USB identities, and run the isolated timing A/B,
repeated mixed-message speed boundary tests, and the five-minute multipage
LoRa capture/recovery test. Only then choose and verify any production cap
or tuning changes. No commit or push was performed for this checkpoint.

## Follow-up: 13 October 2026

The original checkpoint above is historical. Its implementation and Reader /
RS232 integration were subsequently pushed as `0be4c7488` and `396304822`.

- The receiver now keeps its timing estimate in Q5 rather than whole
  milliseconds, eliminating the rounding deadband without changing its
  4168-byte production allocation. Letter/word split thresholds of 2.25/5.5
  dot units tolerate ordinary +/-20% gap jitter; doubled letter spacing
  remains explicitly ambiguous, not a supported exact-decoding result.
- A volatile, default-off HIL transmitter injects seeded phase jitter,
  gradual speed drift and modest extra spacing. Its exact pre-key duration
  check retains the 180-second ceiling. Shipping images contain neither
  the HIL configuration nor its command branch.
- Fresh focused verification passed 108/108 tests. The real HIL scheduler
  and receiver passed 154 exact human-timing vectors through experimental
  240 WPM; 84 additional supported synthetic vectors passed. These are
  software tests, not physical RF speed qualification.
- The CI stability group passed 106/106. The bridge recovery fixture now
  includes the actual RS232 power/heartbeat helpers and verifies byte-exact
  retained short writes. Source/published documentation links passed 7/7
  tests plus browser-script checks.
- Compact STM32 USB Companion links at 228868/229376 flash bytes with
  unchanged commands and ITU character support. An exhaustive 256-byte
  comparison verifies the compact ASCII lookup against the original.
- All four nRF52 HIL targets compiled. Fresh application-only DFU packages
  were installed on the identity-bound RAK4631, MeshPocket and T096 without
  changing their bootloaders or SoftDevices.
- A five-minute remote receive session expired and restored LoRa. All 424
  captured characters were returned exactly in four LoRa pages, but the
  decoded RF text did not match the nine transmitted messages: this is a
  transport/recovery pass and a decoding failure, not an overall pass.
- Six-second no-intentional-TX controls at 902.1 and 903.1 MHz were empty
  on the RAK, but produced false characters on the MeshPocket. A subsequent
  25-WPM alphabet/digit message decoded exactly from Pocket to RAK; the
  reverse direction had errors. One clean message does not establish a
  zero-error speed limit.

RF investigation and repeated standard/uneven-timing speed qualification
remain in progress. Default 25 WPM, public ceiling 60 WPM, radio bandwidth,
and shipping RF filtering have not been changed. Packet control stays at
909.5 MHz / 500 kHz / SF5 / CR5; CW remains separate at 902.100 MHz by default.
Raw results remain in `out/morse-rx/` and the Pi run directory above.
