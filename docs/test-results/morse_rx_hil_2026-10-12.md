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

## Controlled speed and human-timing follow-up

These are **conditional laboratory results**, not a promise of error-free
reception on every board or with automatic noise detection. CW stayed at
902.100 MHz, packet control at 909.5 MHz / 500 kHz / SF5 / CR5, and requested
chip TX power at -9 dBm. The Pocket / RAK pair used a volatile **HIL-only
-80 dBm receive floor** against strong received tones. Shipping images do not
contain this receive-floor setting. Earlier automatic-threshold quiet controls
produced false characters on the Pocket and T096; that remains a separate
qualification limitation.

The original 2.25 / 5.5-dot letter / word boundaries failed ordinary uneven
timing even at 25 WPM. With seeded +/-20% phase jitter, gradual -10% duration
drift, and **no extra letter or word spacing**, the first sweep passed only
2/6 messages at each of 25, 60 and 120 WPM. A short, fully retained RF trace
decoded `VW MN DOG` as `VW MNDOG` in all six directions/rate combinations.
All 20 expected marks remained present; the second word gap measured
246 / 246 ms at 25 WPM, 100 / 102 ms at 60, and 54 / 52 ms at 120. The old
word thresholds were 264, 110 and 55 ms respectively.

The receiver now uses the ordinary **2 / 5-dot gap midpoints**, without changing
mark classification, RX allocation, RF filtering or the public speed limit.
The same tight human-timing profile (seed 6789), with two repetitions of all
three mixed alphabet/digit, word and punctuation messages in both directions,
then passed strictly:

| Requested WPM | Pocket to RAK | RAK to Pocket | Total exact messages |
| --- | --- | --- | --- |
| 25 | 6/6 | 6/6 | 12/12 |
| 60 | 6/6 | 6/6 | 12/12 |
| 120 | 6/6 | 6/6 | 12/12 |

Only leading/trailing capture whitespace is removed in the physical harness;
extra internal spaces, noise characters, missing letters and `?` fail the test.
There were no cleanup errors. This establishes zero observed errors in those
36 messages under the stated laboratory conditions, not universal 100%
reliability or a 120-WPM release qualification.

The production-equivalent RF comparison uses cold-XOSC TX, 3400-us PA ramp,
RSSI window 0, two-ms sampling and ordinary OFF debounce. Compile guards and
actual PlatformIO/SCons flag tests prevent faster experimental settings or a
different receiver clock from being mislabeled as shipping RF behavior.
The lab maximum override and diagnostics still make these HIL applications,
not release images.

Requested WPM is not measured RF pace. Four strict 13-word `PARIS` trials per
rate transmitted 643 dot units, omitting the unsent final seven-unit word gap:

| Requested WPM | Host-observed duration | PARIS-equivalent pace |
| --- | --- | --- |
| 60 | 14.354-14.365 seconds | 53.7 WPM |
| 120 | 7.937-7.940 seconds | 97.2 WPM |

The pace includes CLI response and polling overhead; it is not an oscilloscope
measurement of RF edges. It also does not substitute for varied-text testing.

Latest focused verification passed 129/129 test methods. The actual HIL
scheduler / decoder matrix has 175 exact results plus one explicitly
unsupported 240-WPM / two-ms-sampling / 50%-extended-spacing case. The separate
human envelope matrix has 84 exact results plus 14 explicitly unsupported
doubled-character-spacing cases. Unsupported transcripts remain checked and
visible; they are not normalized or counted as exact-decoding passes.
Former-threshold negative controls reproduce the tight-gap failure. The
production receiver remains 4168 bytes, and compact STM32 still links at
228868/229376 flash bytes with its unchanged feature boundary.

Evidence filenames in the directories above:

- `squelch80-production-rf-human-tight-20261013.json` (before gap correction)
- `production-tight-gap-trace-20261013.json` (complete short RF traces)
- `production-tight-gap-fixed-repeat-20261013.json` (36/36 corrected messages)
- `production-pace-baseline-20261013.json` (host-inclusive PARIS pace)

The tested application-only gap-correction packages were:

| Package | SHA-256 |
| --- | --- |
| `RAK_4631_companion_radio_usb-prod-rf-gap-20261013.zip` | `26cc93db4f6a602e24a35828cca79efaef002b13b18192fe763eb5426515ec6b` |
| `Mesh_pocket_companion_radio_usb-prod-rf-gap-20261013.zip` | `9d1f76c1cc42e1d30ca5daa3d30fe30232d426d72b80278cac67d2d98c21a178` |

The T096's earlier image and measurements do not qualify its speed under this
new gap correction. No LR1110 or SX127x physical speed limit is established by
the SX1262 pair. Default 25 WPM and the public 60-WPM ceiling remain unchanged.

The next faster **production-RF** timing buckets did not meet the zero-error
criterion, even with the same HIL receive floor:

| Requested WPM | Standard timing | Tight human timing, two repeats |
| --- | --- | --- |
| 130 | 5/6 | 11/12 |
| 150 | 2/6 | 6/12 |
| 170 | 0/6 | Not repeated in this corrected sweep |
| 200 | 0/6 | Not repeated in this corrected sweep |

At 130 and 150 some failures affected the initial short mark; 150 also had
later body errors. The first RF mark currently begins before the command
reply and the remaining foreground-loop work. That is a possible delay window,
not a measured explanation of all these errors. No unproved transmitter or
mark-classifier adjustment was made to improve the reported score.

Additional boundary evidence:

- `production-gap-fixed-standard-boundary-20261013.json`
- `production-gap-fixed-human-boundary-20261013.json`

A second human-style pattern, using +/-20% jitter, gradual **+10% duration
drift** (slowing down), no extra gaps and seed 12345, passed another 6/6 mixed
messages at each of 25, 60 and 120 WPM in both directions. Across the corrected
speeding-up and slowing-down profiles, that is 18/18 messages at each rate,
54/54 overall, under the same controlled receive threshold.

The subsequent 30-second **automatic-threshold**, no-intentional-TX control
was not clean overall: the RAK captured `E E `, while the Pocket was empty.
This is evidence against an unconditional production zero-error claim; it is
not a diagnosis of the source of the quiet RSSI excursions. The current
shipping speed ceiling remains unchanged.

- `production-gap-fixed-human-slowing-20261013.json`
- `production-gap-fixed-auto-quiet-20261013.json`

Short, fully retained two-second initial-window traces sharpen the initial-mark
finding. At 130 WPM, the failed first `E` measured 18 ms, exactly twice the
nominal nine-ms unit; a successful first `E` measured 16 ms. At 150, the
corresponding failed/successful widths were 16/14 ms against an eight-ms unit.
Those widths were also common among later dots, so these recordings do **not**
show an unusually long first mark. The later learned units were 11/10 ms,
making comparable later dots classify correctly. Two-ms sample phase and the
initial untrained threshold can therefore matter near this boundary. The
trace has no transmitter deadline timestamps and does not prove that CLI work
caused the errors. These partial diagnostic captures are not complete-message
qualification failures or passes.

- `production-initial-mark-trace-20261013.json`

## Faster experimental RF comparison

The corrected fast SX1262 HIL applications use warm-XOSC TX, an 800-us PA
ramp, RSSI window 2, one-ms sampling and the experimental short OFF-confirmation
minimum. These are **not shipping RF settings**. The same -80 dBm HIL receive
floor and exact-message checks were used on the same Pocket / RAK pair.

| Requested WPM | Standard timing, two repeats | Tight human timing |
| --- | --- | --- |
| 120 | Previously all-pass; not repeated in this boundary sweep | 6/6 |
| 150 | Not tested in this boundary sweep | 5/6 |
| 200 | 12/12 | 3/6 |
| 255 | 10/12 | Not tested in this boundary sweep |

The tight human profile is again +/-20% jitter, -10% duration drift, no
added letter/word spacing and seed 6789. At 150, `DOG` became `DKG` in one
direction. At 200, three messages had real body or punctuation errors.
The shortest timing bucket therefore does not qualify as zero-error, and
neither does the higher uneven-keying speed. Integer rounding maps requested
219-255 WPM to the same five-ms dot, so 255 is not 255 measured WPM.

The fast steady-PARIS pace check gives:

| Requested WPM | Host-observed duration | PARIS-equivalent pace | Exact PARIS messages |
| --- | --- | --- | --- |
| 120 | 6.868 seconds | 112.3 WPM | 2/2 |
| 200 | 4.273-4.277 seconds | 180.5 WPM | 2/2 |
| 255 | 3.669 seconds | 210.3 WPM | 1/2 |

The failed 255 PARIS capture contained `PANIS` in place of one `PARIS`.
These rates include the same host/CLI overhead as the production-equivalent
pace measurement; pace is calculated only for the 643-unit PARIS payload,
not by applying that reference count to the other test messages.

The strongest observed all-pass points are therefore **200 requested WPM
for machine timing on the fast HIL pair**, and **120 requested WPM for the
tested uneven timing**. Their steady-PARIS references are approximately
181 and 112 WPM respectively. With production-equivalent RF timing, the
tested uneven-timing reference is approximately 97 WPM. None of these
conditional limits resolves the automatic-threshold quiet-control failure
or qualifies another board/radio family. Shipping defaults remain unchanged.

- `fast-gap-fixed-standard-max-20261013.json`
- `fast-gap-fixed-human-boundary-20261013.json`
- `fast-gap-fixed-pace-20261013.json`

| Fast HIL package | SHA-256 |
| --- | --- |
| `RAK_4631_companion_radio_usb-fast-gap-20261013.zip` | `7722ca7a0008c660217535c19e9dd17d5923fc90510f9850b2ce188a6d753951` |
| `Mesh_pocket_companion_radio_usb-fast-gap-20261013.zip` | `8d153c544f19e01d45e178105b704840f855a53cb8fda2044ba102cb19b85521` |

Final cleanup confirmed both selected radios had Morse stopped, configured
25 WPM / 902.100 MHz, default HIL timing and automatic squelch restored.
Their saved primary settings still held an earlier 919.5-MHz lab tuple; those
two test devices were explicitly changed to **909.5 / 500 / SF5 / CR5**, and
that tuple was also confirmed live. No service radio was changed. The pair
remains on the identified fast HIL applications, not shipping images.
