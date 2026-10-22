<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/esp32_ble_radio2_sleep_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# ESP32 Bluetooth shutdown and radio2 CPU idle, 2026-10-21

The ESP32 changes cover two gaps identified while qualifying nRF52 CPU sleep:
reversibly stopping the Bluetooth host/controller, and allowing bounded MCU
light-sleep during a settled secondary-radio receive visit. This report
separates host/build coverage, SDK wait measurements and physical packet tests.

Bluetooth transitions and quiet-window SDK wait checks pass. Three earlier strict RF trials with
power saving on and
matched preambles received five of six packets, including the trial after the first IRQ fix. They remain
failures; radio2 is not fully qualified.

The first V3 CPU-clock sweep stopped during setup, before any of its
20-packet-per-frequency cases transmitted. Switching Bluetooth off exposed a
NimBLE-Arduino 2.5.1 shutdown crash: PC zero in the host task, with the event
address resolving to `ble_hs_timer + 8`. This matches upstream
[issue #1184](https://github.com/h2zero/NimBLE-Arduino/issues/1184) and its
[merged fix #1185](https://github.com/h2zero/NimBLE-Arduino/pull/1185).
The backport removes premature timer deinitialization while leaving final
cleanup intact. The earlier V4 Bluedroid checks do not qualify V3 NimBLE.
The regression reproduces the original null callback, then passes 1,000
shutdown/cleanup cycles under ASan/UBSan for each timer backend. Library
version, source hash and build-local middleware checks also pass.

Full Companion source
[`6236eec3`](https://github.com/mikecarper/MeshCore/commit/6236eec386b5450b739a206923a442692eb74f90)
includes that repair and a preferences-reader fix for a truncated timezone
record colliding with the new CPU footer length. Both timezone and CPU suites
pass; damaged CPU overrides still fall back to Auto. V3 and V4.3 OLED FEM-off
builds pass all 24 capability markers and their memory gates, at 2,118,680 and
2,556,504 application bytes respectively.

The V3 received one application-only update after its old application hash
was verified. Complete new-image readback passed, with its partition table
and OTA metadata unchanged. Starting with Bluetooth saved off, it restored
Bluetooth on and completed three off/on cycles without a reboot or core
error. Uptime advanced from 32 to 58 seconds across 20 health samples. Every
Binary handoff revalidated board identity and source version. The final
checked configuration and credential hashes matched the baseline, and the
active PIN stayed unchanged. This physical check covers Bluetooth power
transitions, USB control and checked preference preservation.

The recovery also exposed an already-ROM ESP32-S3 UART finish gap. The flasher
now explicitly releases the boot strap before its final reset; its regression
passes with both esptool command spellings. That separate fix is published in
[meshfirmware `f9d03d1`](https://github.com/mikecarper/meshfirmware/commit/f9d03d1).

## Behavior and safeguards

Bluetooth off disconnects clients and completes host/controller teardown in
the main loop. Bluetooth on rebuilds the service without releasing controller
memory permanently or clearing successful bonds. Address, name, PIN and saved
stealth policy remain intact. Pending or failed teardown prevents CPU sleep.
The Bluedroid characteristics have deterministic TX/RX registration order;
heap fragmentation must not change a paired client's cached handles. On SDKs
using automatic Service Changed handling, a small asynchronous service change
requests client rediscovery after authentication. A local SDK completion is
not treated as proof that the client refreshed its cache. Only actual use of
the current notification and receive handles permits skipping this request on
a later connection from the same peer within that host session.

Companion, Repeater, Room Server and Sensor can idle during an eligible
radio2 visit. The decision requires a settled, validated receive profile,
working radio GPIO wake, no pending reception and physically stopped wireless
drivers. An absolute scanner deadline is checked again at sleep entry. The
timer budget is at most 10 ms, reserves a 4 ms early-wake scheduling guard and
requires at least 2 ms remaining. Calibration, repair, ownership, queue,
network, USB and role deadlines retain their existing guards. The receiver
stays on. This does not enable sleep through an active Bluetooth/WiFi link.

## Host tests and builds

The scheduling, board wake, dispatcher and real role integration suites pass.
Coverage includes expired and wrapping deadlines, stale profile proofs,
pending interrupts, failed wake setup and SDK errors. The BLE adapter tests
exercise actual production code with ASan/UBSan, ownership differences,
partial initialization/teardown failures and repeated off/on cycles. Existing
nRF52 event/profile tests also pass; nRF52 hardware was not touched.

All 22 scripts in the affected Sensor/tracker/sleep CI step and all 57 in the
Companion contact/channel step pass locally. The latter initially encountered
a missing Python `platformio` module in one read-only metadata case; that
script's six cases passed with the existing PlatformIO Python environment.
No firmware build or hardware test was repeated for this environment correction.
The diagnostic fixtures exercise the current production sleep branches rather
than relying on obsolete source anchors.

The initial sleep/teardown implementation, before the cache fix, has Full
V4.3 FEM-off Companion, V3 Companion, V4 Repeater, Room and Sensor builds that
pass their capability and memory gates. ESP32-C6 BLE (Arduino 3.1.3), the
NimBLE-Arduino V4 trial and RC32 Full (Arduino 3.3.11) also compile. RC32
exposed SDK service ownership and array-deletion defects; a version/hash-bound
build-local repair fixes those sources without editing a shared SDK install.

The cache fix is published in
[`1087643ae`](https://github.com/mikecarper/MeshCore/commit/1087643ae867b9a8746f00b3ff43d574b59e2457).
Its V4.3 FEM-off Full and RC32 Full builds pass all 24 capability markers and
their application size gates: 2,551,592 and 2,152,840 bytes respectively, each
within a 6,553,600-byte application slot. The other earlier builds do not
constitute a full build matrix of this later source revision.

[`d34e65175`](https://github.com/mikecarper/MeshCore/commit/d34e65175b856e24eee6c9ac9053f732eb869bd1)
removes unnecessary delays between successful cache-recovery phases while
retaining bounded failure backoff. Its V4 Full build passes, at 2,551,608 bytes.
The same-size V4 build of
[`f8b5b8301`](https://github.com/mikecarper/MeshCore/commit/f8b5b8301e55e97058342f293b13b559c8f9144b)
adds only the channel-response padding fix described below. Bluetooth, radio,
sleep-policy and role code are unchanged between those last two revisions.

Classic Heltec V2 BLE remains below its required 8,192-byte internal RAM
reserve. Historical checks left 2,552 bytes free on the baseline and 1,224 bytes
on the initial sleep candidate. Removing an unnecessary WiFi-driver reference
recovered 1,208 bytes, raising the later candidate to 2,432: 120 below baseline
and 5,760 short of the reserve. Final cache/padding revisions were not
remeasured on V2. The gate was retained; this target remains unqualified.

## Physical V4 observations

The test board is a Heltec V4.3 OLED using its matching FEM-off Full Companion
image. The first candidate reports source suffix `278c9ffb`; its published
equivalent after history cleanup is `61eecbd97`. An application-only write and
complete readback preserved the partition table, OTA metadata, identity,
settings and credential digests. No whole-flash backup, bootloader write or
other-device update was performed.

With Bluetooth/WiFi off and power saving on, only this V4's USB data was
suspended. After the host-loss grace period, a 90-second diagnostic window
recorded **4,635 SDK light-sleep calls and returns**, zero SDK errors, zero
short waits, zero vetoes and zero pending-wake returns. Cumulative call time
was 35.523299 seconds; the longest call was 9,869 microseconds. The mixed
profiles were 910.525 MHz / BW62.5 / SF7 / CR5 and 916 MHz / BW125 / SF9 / CR5.
USB authorization and runtime policy were restored. Core errors remained zero.
These are SDK wait measurements, not electrical current or residency readings.

Two initial saved-bond Bluetooth off/on sessions passed. Further testing
exposed both a host-side notification-acquisition problem and a real firmware
GATT-handle ordering defect. The host driver now uses ordinary StartNotify.
The original failures are retained; clearing a client cache is not accepted
as proof that firmware handles remain stable or an existing cache migrates.

On `d34e65175`, both authenticated NUS connections passed with the old opposite
handle cache retained. The test independently checked board, exact version,
role, public identity, node name, address and advertising policy. Switching off
while connected disconnected the client; the test required completed off
before re-enabling and reconnecting. No cache was cleared and no new pairing
was made. The cache changed automatically to TX value `0x002A`, RX value
`0x002D`; saved pairing-key digests were unchanged. The image also started
successfully with Bluetooth saved off. No electrical power measurement was made.

## Two-frequency packet controls

The peer is an independently identified ESP32 XIAO S3 WIO. Every transmitted
packet uses a new encrypted nonce, full sender/destination identities and a
zero-hop direct route. The receiver's USB data is absent during the sleeping
RF window; queued packets are checked only after USB resumes. WiFi and
Bluetooth are stopped, crossover is off, and physical RX counters must advance
on both frequencies. No failed packet is resent automatically.

Earlier runs used a transmitter preamble of 128 symbols while the receiver
reported 32. An awake two-packet control received zero packets with zero SDK
sleep calls. Disabling radio2 then received the one primary test packet.
Source inspection found that the receiver's 32-symbol preamble guards expire
after about 99/198 ms, while a 128-symbol transmitted preamble alone lasts
262/524 ms on these profiles. The guard can clear preamble detection and permit
a scan hop before the header arrives. These mismatched trials remain recorded;
they do not establish a CPU-sleep regression.

With both sides at the verified 32-symbol preamble and peer TX at 2 dBm:

| Control | Unique packets received | SDK waits | Result |
| --- | --- | --- | --- |
| USB active, CPU awake | 2/2; one on each profile | 0 | Pass, including exact cleanup |
| USB suspended after 121-second host-loss grace, power saving on | 5/6; all three primary and two secondary | 777 calls/returns; zero SDK errors, short waits, vetoes or pending returns | Strict RF check failed: final secondary nonce missing |

The sleeping trial's measured profile RX deltas were 100/2, including ambient
traffic. Both frequencies carried verified private packets while the MCU idle
path ran, but the missing sixth packet prevents an all-pass result. These
finite samples do not establish a loss rate or attribute that loss to CPU sleep.

A predeclared paired comparison then used the same `d34e65175` image, settings,
32-symbol preambles, TX power and suspended USB in both modes. Each interval
sent six new nonces once. A first preparation attempt was refused before any
RF transmission; its clean restoration and zero-transmission receipt remain
preserved. Bounded admission of the power setting was moved before USB
suspension; no packet retry was introduced. Power saving also caps the CPU at 80 MHz;
switching it off restores the nominal 160 MHz clock on this V4 Full build.
This comparison measures the whole power-saving policy, so it does not isolate light sleep from foreground
CPU speed.

| Same-image control | Unique packets received | SDK calls/returns | Result |
| --- | --- | --- | --- |
| Power saving off | 6/6; three on each frequency | 0/0; all diagnostic error/veto counters zero | Pass, cleanup and PS-on restoration verified |
| Power saving on | 5/6; primary sequence 2 missing, all three secondary packets received | 820/820; zero errors, short waits or pending returns; five vetoes | Strict RF check failed; cleanup and PS-on restoration verified |

The second sleeping trial had profile RX deltas 103/3, including ambient
traffic, and seven receive errors. The different missing packet rules out a
deterministic final message-slot loss. This small comparison warrants a wake-path
investigation; it does not isolate interference, scanner timing or an individual
GPIO event as the cause. No unchanged RF trial was repeated after it.


## GPIO wake and packet ownership

[ESP-IDF 4.4.7 documents](https://github.com/espressif/esp-idf/blob/v4.4.7/docs/en/api-reference/system/power_management.rst#L30-L34)
that GPIO interrupts are not generated during light sleep. GPIO wake is a
separate mechanism. The board temporarily uses a level wake source and then
restores a rising-edge interrupt; the SDK's
[GPIO driver](https://github.com/espressif/esp-idf/blob/v4.4.7/components/driver/gpio.c#L132-L140)
and [S3 wake implementation](https://github.com/espressif/esp-idf/blob/v4.4.7/components/hal/esp32s3/include/hal/gpio_ll.h#L299-L313)
do not replay a software callback when that interrupt type is restored.

The wrapper previously checked only its software event. If a completed packet
left DIO high without a callback, the loop could fail to claim its FIFO before
a later rearm or retune. This is a concrete ownership gap, but the aggregate
packet results do not prove which missing nonce encountered it.

[`1ba4e2830`](https://github.com/mikecarper/MeshCore/commit/1ba4e283085c02826f593f9a70609b20f3c22bdd)
adds an ESP32-only physical IRQ fallback to both pending and claim checks. It
uses that registered radio module's own pin and HAL, validates ownership,
null pointers, NC, pin range and the SoC validity mask, and adds no RAM fields.
Claiming consumes any software event too; the unchanged hardware RX_DONE
check still gates FIFO reads. It changes no frequency, preamble, wake mask or
sleep budget. Other platforms retain their software-event behavior.

All 12 interrupt-recovery host tests pass with ASan/UBSan. They execute the
production receive and reconfiguration paths with an asserted DIO and no ISR,
combined and delayed callbacks, independent radio pins, invalid pins and
non-ESP32 variants. Removing either fallback fails an executed regression assertion.
The V4 Full build passes all 24 capability markers and its memory/size gates,
at 2,551,736 bytes within the same 6,553,600-byte application slot. The RC32
Full build on Arduino 3.3.11 also passes all 24 markers and its memory/size
gates at 2,152,968 bytes. These are build checks, not physical RC32 qualification.

The application-only installation and full readback of this image passed,
including unchanged partition table, OTA metadata, identity, saved settings and
credential digests. One new six-packet qualification trial then exercised the
changed IRQ code with the same radio settings, USB suspension and power-saving
policy. It received **5/6**, missing secondary sequence 6: another strict RF
failure. All six sends completed once; none was resent. Profile RX deltas were
79/2, including ambient traffic, with five direct packets and two receive errors.
The interval recorded 741 SDK calls/returns, zero SDK errors, short waits or
pending returns, and two safe vetoes. Cumulative call time was 5.710857 seconds;
the longest was 9,900 microseconds. Cleanup and PS-on restoration passed.

Independent source audits found no additional concrete clock/deadline defect:
ESP32 `micros()` and the scanner use the ESP Timer domain; the deadline is
anchored before the late query and checked again after wake setup. Pending
packets and latched preamble/header activity guard the next retune. The current
4.6-symbol scanning model is not a zero-loss guarantee. The observed losses
remain unresolved; neither interference nor the IRQ gap is established as their
cause. No further unchanged RF trial or arbitrary timing/preamble change was
used to obtain a pass. Further qualification needs a control that holds CPU
speed fixed and correlates scan/preamble/IRQ timing with individual packets.

## Channel cleanup and response padding

The single-profile and sleeping reports also recorded cleanup failures. The
single-profile power restore was refused while the radio was busy; a separate
bounded cleanup restored 22 dBm and removed only the hash-matching test channel.
The later sleeping run restored power and cleared its channel but failed a raw
channel-response digest comparison.

A separate read-only audit compared every meaningful channel name and every
key byte twice on both devices. All matched, and both temporary slots were
empty with zero keys. Raw differences occurred only after the terminating NUL
in the fixed-width channel-name field: one channel differed between repeated
reads on each device and all 40 differed between devices. The getter used
`strcpy` without clearing the unused name bytes, exposing stale reply-buffer
padding. The original failed receipts were retained; no channel data was
rewritten to force a digest match.

The shared Companion fix zero-pads and bounds that field while retaining key
offset 34 and the existing 50/66-byte frame layouts. All nine affected host
tests pass. The actual-handler regression covers empty, short, maximum and
unterminated names, dirty output buffers, Meshtext on/off and 16/32-byte keys;
the original implementation fails its negative control.

A read-only hardware audit on `1ba4e2830` also passed: both devices' meaningful
channel names and every key byte matched across two reads, both temporary
slots were empty with zero keys, and every V4 name field had zero padding.
The peer's firmware was not changed.

## V3 fixed-clock comparison with 20 packets per frequency

After the NimBLE repair, the V3 completed all four predeclared cases on
`6236eec3`. Every case sent 20 unique packets per frequency once, with the same
32-symbol preambles, 2 dBm peer TX power and default 10/4/2 ms sleep dials.
Power saving stayed on; CPU speed and the temporary manual sleep switch were
controlled independently. RX power saving was saved off for these comparisons;
the profile scanner itself uses continuous RX during each visit.

| CPU | Manual CPU sleep | Primary received | Secondary received | SDK calls/returns over the whole diagnostic window |
| --- | --- | --- | --- | --- |
| 80 MHz | Off | 18/20 | 17/20 | 0/0 |
| 80 MHz | On | 20/20 | 19/20 | 270/270 |
| 160 MHz | On | 18/20 | 14/20 | 18/18 |
| 160 MHz | Off | 19/20 | 16/20 | 0/0 |

All 160 transmissions reached TX_DONE, with no packet retries or duplicates.
All four strict delivery checks failed. Settings, channels and credential
hashes were restored; both radios finished with zero core error flags.
Losses with manual sleep off show that sleep is not required for the observed
failure. Ambient traffic differed between cases, and these samples do not
establish a CPU-speed relationship or a packet-loss cause.

The On rows do not yet prove sleep during packet traffic. The UART quiet
control stopped the driver but left its Companion session logically connected.
Incoming messages then queued push notifications to that stopped transport;
the existing pending-output guard correctly prevented sleep. Whole-window SDK
calls could have occurred before traffic began. The delivery counts remain
valid, but sleep comparison qualification requires retiring that UART session
and timing evidence inside the RF sequence. No pending-work guard is bypassed.

## UART session repair and timed V3 comparison

The campaign continued on 2026-10-22 with
[`7d0709bf0`](https://github.com/mikecarper/MeshCore/commit/7d0709bf03aa53f3a31467f1ed1496e24824a7c8).
UART quiet now retires only that USB protocol session after draining the ACK,
including its pending reply owners and USB Reader output. The offline inbox
and other transports remain active. A successful UART restart restores a
fresh silent session; failed restarts keep the interface parked and retry.
The integration regression reproduces the original stuck notification, then
retains and downloads 40 actual receive frames without weakening sleep guards.

ESP32 diagnostics now retain sixteen 16-second SDK-entry buckets, with explicit
outside-window, saturation and missing-clock indications. The collector stays
within its 256-byte budget; nRF52 layout and behavior are unchanged. The
physical comparison requires a positive bucket wholly after the first confirmed
TX_DONE and before the last TX request, including host/device clock uncertainty.
This establishes SDK entries during the packet sequence, not sleep through a
particular packet or electrical residency.

Both Full Companion builds passed 24 capability markers and their memory gates.
V3 and V4 application sizes are 2,120,088 and 2,557,400 bytes. Application-only
updates passed full readback, unchanged partition/OTA metadata and checked
configuration/credential preservation on both boards. No Bluetooth lifecycle
or earlier quiet-only test was repeated solely for documentation changes.

The new V3 comparison again sent 20 unique packets per frequency per case,
with no RF retries, the same 32-symbol preambles and default sleep dials:

| CPU | Manual CPU sleep | Primary received | Secondary received | SDK calls/returns | SDK calls in wholly contained RF-time buckets |
| --- | --- | --- | --- | --- | --- |
| 80 MHz | Off | 17/20 | 15/20 | 0/0 | 0 |
| 80 MHz | On | 18/20 | 19/20 | 10,925/10,925 | 4,625 |
| 160 MHz | On | 18/20 | 16/20 | 10,164/10,164 | 4,585 |
| 160 MHz | Off | 20/20 | 16/20 | 0/0 | 0 |

All 160 sends reached TX_DONE once; there were no duplicate deliveries. All
four strict delivery checks failed. On cases have positive SDK activity during
the RF sequence, with zero SDK errors, short returns or pending waits. In the
80 MHz On comparison, serial blocking fell from 109,265 ms on the old image to
1,368 ms after session parking. This supports the console-fix mechanism; varied
ambient traffic still prevents a causal delivery comparison. Neither CPU speed
nor manual sleep consistently removed packet loss. Original settings, channels,
identity and checked credential hashes were restored, with clean core flags.

V4's first new comparison stopped during setup, before Bluetooth-off was sent
and before any case or RF transmission. Its strict stable-Binary check rejected
one unexpected prefix byte after a valid health response. Seven valid push
frames were accepted; the rejected byte was not retained, so its origin was
unknown at the time. That original failure remains recorded.

Two diagnostics-only attempts on unchanged `7d0709bf0` also stopped before
Bluetooth-off was sent, with zero RF transmissions. Bounded raw capture retained
the late SDK line `E (2905571) wifi:timeout when WiFi un-init, type=4`.
Source inspection identified an SDK timer firing after shutdown; this message
does not establish that WiFi deinitialization timed out. The raw SDK log
bypassed disabled USB logging and broke strict Binary Companion framing.
All three attempts restored checked settings/channels and verified a fresh
MQTT PUBACK increase. The latest immutable diagnostic receipt is
`v4-7d0709bf-suffix-completed.private.json`. These setup failures supply no
new V4 packet-delivery evidence.

## SDK logging repair and V4 scanning controls

The SDK logging fix in `d73599bc6` shipped in
[`3fd9b392`](https://github.com/mikecarper/MeshCore/commit/3fd9b392c8d216e2d5dd592587085c1a71fa738c).
It prevents raw SDK logs from bypassing the disabled USB-logging policy and
corrupting the shared Binary Companion stream. All 101 USB host tests pass.
The V4 application is 2,558,856 bytes, with SHA-256
`ddfd4f40a97da40bdeda2c00fb18ebc2d4d365590d4bc63496a425d16975906d`.
Its installation passed full readback and checked configuration preservation.

Two new scanning cases completed on this V4 image, with 20 new nonces per
profile, matched 32-symbol preambles and 2 dBm peer TX:

| CPU | Manual CPU sleep | Primary received | Secondary received | SDK calls/returns | SDK calls in wholly contained RF-time buckets |
| --- | --- | --- | --- | --- | --- |
| 80 MHz | Off | 19/20 | 18/20 | 0/0 | 0 |
| 80 MHz | On | 19/20 | 15/20 | 4,121/4,121 | 3,511 |

Both strict delivery checks failed. All 80 sends reached TX_DONE once, with
zero retries or duplicate deliveries. SDK errors, short returns and pending
waits were zero. The awake losses establish that CPU sleep is not required for
this symptom; these samples do not identify the cause of individual misses.

The user redirected testing toward the scanner. The 160 MHz On case was
intentionally stopped during its USB host-loss grace period, before any RF
transmission; 160 MHz Off was not entered. This is not a completed four-case
comparison. The interrupt receipt remains recorded in
`v4-3fd9b392-user-steered-completed.private.json` (SHA-256
`e102200af7e2503bb0362e65afad0d947d5c3aeb220425a589d0588032530c52`).
Full restoration and a fresh MQTT PUBACK increase passed after that stop.

## Fixed-tuple controls and receive-path defect

Two fixed-tuple controls on the same `3fd9b392` image each received **20/20**
unique packets with radio2 explicitly off. The primary physical radio was
temporarily tuned first to 910.525 MHz / BW62.5 / SF7 / CR5, then separately to
916 MHz / BW125 / SF9 / CR5. Both runs used 80 MHz, manual CPU sleep off, saved
power-saving intent on, RX power saving off, 32-symbol preambles and 2 dBm peer
TX. The target's USB data was absent after the same 121-second host-loss grace.
Each run retained the original seeded 40-slot cadence, leaving the opposite
profile's 20 slots silent. SDK calls, duplicate deliveries and RF retries were
zero. The immutable control report remains failed because the peer's original
22 dBm setting was not restored within three bounded busy-response attempts;
MQTT recovery passed. A separate recovery then restored 22 dBm and verified
full peer settings, credential hashes and channel semantics without another
RF transmission. The original failure is retained in
`fixed-tuples-v4-3fd9b392-completed.private.json`; successful recovery is in
`peer-tx22-restoration-verified.private.json`.

These finite controls narrow the investigation toward scanning or overlapping
traffic. Radio2 time-shares one transceiver: a valid primary reception can
occupy it throughout a secondary packet's preamble. The idle-scan timing model
does not guarantee zero loss under simultaneous traffic. The controls do not
distinguish that limitation from a receive-path defect for a particular nonce.

A separate host regression executing the real receive functions with
ASan/UBSan proved a stale-IRQ defect. Servicing a packet through its asserted
physical DIO could leave a late software event. Subsequent empty RX_DONE probes
could then restart continuous RX over a newer packet's preamble or valid
header. The narrow ESP32 SX126x continuous-RX guard in
[`a5293fa50`](https://github.com/mikecarper/MeshCore/commit/a5293fa50b2d957077c5fdcb9378b6e88370d9d5)
preserves that new reception while retaining normal activity timeouts.
All 15 interrupt-recovery, five receive-contract and six RX-retry tests pass.
The V4 build passes all 24 capability markers and its memory gate at 2,558,936
application bytes. Its application SHA-256 is
`cc16e44ccd24e64724a2bd17f59f684117e411077e4c0a7d04611be328b7ccfc`.
The application-only installation passed complete readback, with the partition
table, OTA metadata and checked configuration preserved. The immutable receipt
is `flash-v4-a5293fa5-completed.private.json` (SHA-256
`ef61cf8dfc77f8907d621f7f0493949ff6888b017c277eefb309247ccf88b278`).

One new awake 80 MHz scanning run then sent 20 unique packets per profile on
this changed image, with manual CPU sleep off and the same matched preambles,
TX power and USB host-loss grace. The V4 received **19/20 primary and 20/20
secondary packets**. All 40 sends reached TX_DONE once, with zero retries or
duplicate deliveries. SDK calls, returns and all time buckets were zero; core
error flags remained clear. The missing primary nonce keeps the strict RF
result failed. Full restoration passed, including a fresh MQTT PUBACK increase.
The immutable receipt is `v4-a5293fa5-awake-completed.private.json` (SHA-256
`466bdf0bb08f10665007d156e1ec37c074e1c576e6ac5fc401bcd449179ee774`).

The stale-IRQ regression proves a receive-path bug and the new guard repairs
that case. This physical sample does not establish which historical misses
encountered it or show that all scanning losses are fixed. A controlled
two-transmitter overlap diagnostic is recorded below; it does not establish a
cause for these historical misses.

### Receive activity across RX restarts

A further host regression executing the production receive methods exposed a
separate scan hazard. Reading a completed packet and successfully rearming RX
cleared the hardware IRQs but retained the previous packet's `_activityAt` and
`_headerSeen` latches. At the next due scan, the detector could mistake the new
packet's preamble without a header for the old packet's consumed header. It
reported idle before processing that preamble, permitting a retune over the
new packet. The regression reproduces that sequence and shows that resetting
the latches on successful RX entry protects the next preamble.

The change resets those existing fields only after successful receive
starts in `CustomSX1262`, `CustomSX1268`, `CustomLLCC68`, `CustomSTM32WLx`,
`CustomLR1110` and `CustomLR1121`. It covers normal starts and, where supported,
fast resumes and duty-cycle entry. Failed starts retain their prior state;
the change adds no fields and leaves existing activity timeouts and
receive/retune guards unchanged.
Independent source review passed. Five new regression methods cover 24
ASan/UBSan variants, including reset-removal controls that reproduce the
retune over a new packet for all six handlers. All 19 affected host-fixture
tests and 26 interrupt-recovery, receive-contract and receive-retry checks
pass. The new suite runs in the required unit-test workflow. Physical RF
results on the new image are recorded below. The host proof does not attribute
historical missing nonces or establish a complete RF pass.

## RX-restart installation and overlap diagnostic

The V4 image built from pushed source
[`e4119a120`](https://github.com/mikecarper/MeshCore/commit/e4119a1206efefc0506c12ebe529883b966784f5)
passes its capability and memory gates at 2,558,984 application bytes. Its
application SHA-256 is
`fc1a835c45ebc5e7a9fec95c757d8606e145bbc92fa8d365ba62d96a7930286d`.
The application-only installation passed full readback and checked
configuration preservation. The receipt is
`flash-v4-e4119a12-completed.private.json` (SHA-256
`b06d8b6ef8d9df9aa881d6d1ca2f6096d19c8bcc6d4cbb2873fb20d47a9f85c5`).

Two overlap conditions completed on this image at 80 MHz with manual CPU sleep
off. Each condition sent 20 unique primary/secondary pairs; all 40 sends
reached TX_DONE once, with zero retries or duplicate deliveries and zero SDK
counters in both conditions.

| Condition | Primary received | Secondary received |
| --- | --- | --- |
| Radio2 scanning | 16/20 | 2/20 |
| Fixed 916 MHz, radio2 off | 0/20 (outside receive frequency) | 20/20 |

All 20 scanner timing bounds were inconclusive. The nominal 140 ms secondary
write occurred 227.239-263.257 ms after the primary write (median 244.363 ms),
while the first counter reply confirming primary TX_DONE arrived
523.533-903.982 ms after that write. That reply bounds completion; it does not
timestamp the RF event. The controller synchronously saved the report before
the secondary write and after each counter reply, widening these bounds.
The analysis uses 101-byte wire airtimes of 397.824/652.288 ms, a complete
148.480 ms secondary preamble and a 2 ms margin. No pair proves that the whole
secondary preamble fell inside the primary payload reception. The timings
do not exclude desense or attribute historical misses. The ordinary
alternating-profile check is recorded below.

Three earlier setup attempts sent no RF: the first two stopped before
mutation; the third encountered a pending lease, with separate V3 automatic
cleanup recovery passing. The overlap experiment completed with an
inconclusive status: neither condition has a qualified timing pair, so masking
was not demonstrated. Full restoration of all three boards passed without
errors, and a fresh MQTT PUBACK verified recovery. The final host receipt is
`/home/mesh/hwtest/esp32-radio2-pson-v3-v4-20261021/overlap-v4-e4119a12-completed.private.json`
(SHA-256
`c1aee5132b447734df3fe9c663f4f3ae7a8b980f3165de43f96c2653d05200e1`).
No firmware qualification pass is claimed.

## Ordinary awake check after both receive fixes

The predeclared `e4119a120` check sent 20 new packets per profile, once each,
with the ordinary alternating schedule and no deliberate overlapping sender.
It received **17/20 primary and 18/20 secondary packets**. All 40 sends reached
TX_DONE once; duplicates, RF retries and SDK sleep calls were zero. The strict
RF result remains failed. The physical counters recorded 120 successful raw
receives: 35 owned direct packets and 85 ambient floods, with seven separate
receive errors. These totals do not identify the cause of each missing nonce.
The immutable receipt is `v4-e4119a12-awake-completed.private.json` (SHA-256
`9f2f8acecc634ebaf7b9e9aa21e51079b9872316e571a886d3866bfedabab558`).

That receipt also retains a cleanup failure: restoring automatic radio2
permission was rejected while the temporary primary restore was still pending.
Fresh MQTT recovery passed. A separate guarded operation subsequently restored
automatic permission with one setter and no RF transmissions, then verified
the checked settings, credentials and channel semantics against the baseline.
Its receipt is `v4-auto-restoration-after-e411-awake.private.json` (SHA-256
`4dbf10eeac81e8897c8a4f9fa4d7b62ac20e74c91b467a501f31fa3a1d8bd0ec`).

Both receive defects remain proven by executed host regressions, but the
physical results show that additional losses remain. The next diagnostic
records bounded activity and transmission times on the radios themselves.
It must distinguish other-profile ownership, unresolved preamble activity,
read/rearm gaps and delays between scanner calls without treating host counter
replies as RF timestamps. No arbitrary preamble or CPU-sleep setting change
or replacement packet was used to turn a failed result into a pass.

## Final handback and limits

V3 currently runs `7d0709bf0`; V4 runs `e4119a120`, and the peer remains on
`ebb59d48`. The completed earlier V3 campaign and V4 scanning controls,
including the `a5293fa50` awake run, restored their checked radio, RX power-saving,
Bluetooth, WiFi, MQTT, logging, diagnostics and USB-watchdog settings, including
credential digests, original radio2 automatic permission and peer power/channel
state. Fresh MQTT PUBACK increases verified recovery. The fixed-tuple cleanup
power failure is retained, with the later peer recovery verified separately.
Full overlap restoration is verified. The ordinary run's original cleanup
failure is retained, with its separate automatic-permission recovery verified.
No nRF52 board, hub power or other firmware was changed in this task.

The Bluetooth hardware checks pass. SDK light-sleep calls are observed without
SDK errors. Strict sleeping two-frequency packet qualification remains open,
and Classic V2 still fails its existing RAM reserve gate. These results do not
qualify every ESP32 board or the full thirteen-radio fleet, and do not measure
electrical power savings. Unchanged Bluetooth and quiet-wait checks were not
repeated for padding, version, documentation or fixture-only changes.

Private artifacts, receipts and traces are retained under
`/home/mesh/hwtest/esp32-ble-radio2-sleep-cd4ea053-20261021/` and
`/home/mesh/hwtest/esp32-radio2-pson-v3-v4-20261021/`.
See [power-saving diagnostics](../power_saving_diagnostics.md) for the controls
and the limits of interpreting wait counters as energy savings.
