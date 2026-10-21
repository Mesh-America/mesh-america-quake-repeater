<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_ota_1_18_0_1_2026-10-20/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# OTA hardware qualification, 20-21 October 2026 UTC

Status: COMPLETED for the listed OTA cases. Earlier failures and unresolved
observations remain recorded below; this is not a claim that every board or
transport has passed all release qualification.
The operator authorized erasing these test nodes without backups. MeshPocket
remains excluded. No nRF52 bootloader or SoftDevice payload is part of this
campaign. Temporary ESP32 bridge role changes use the board's merged image,
including its ESP32 bootloader and partitions, under the authorized erase.

The initial hardware OTA results use artifacts pinned to
`8b5660b00b88d8abaae094859bc1232f7ce886fd`.
That commit changes documentation only relative to firmware source
`0b207a1ec3a32eb0a8ad6b8643db211de4921cd4`. Separate OTA-check version strings
produce distinct image hashes for controlled update tests. The common numeric
version is `0x01120001`; same-version updates are explicitly authorized for
these tests. They are not claimed as numeric version upgrades.
Later source, CPU-sleep and one-hop results identify their own commits below.

| Device and role | Transport | Result |
| --- | --- | --- |
| Heltec V4.3 Full Companion | Production browser WiFi OTA | PASS: one upload installed the exact intended image; postboot identity, version, core, radio and original flags verified |
| RAK4631 unified repeater | Bluetooth application DFU; QSPI full LoRa OTA; two-frequency bridged one-hop LoRa delta | Transfers and eventual postchecks PASS, including one-hop installation; initial USB version response remains under investigation |
| Seeed XIAO nRF52 repeater | Bluetooth application DFU; external QSPI full LoRa OTA | Transfers and eventual postchecks PASS; initial USB version response remains under investigation |
| RAK3401 unified repeater and gateway | Bluetooth application DFU; internal LoRa delta; gateway restoration | PASS: Bluetooth update and repeater service, internal LoRa delta apply, normal-radio restoration and gateway service handback |
| MeshTower SD repeater | Signed SD-backed LoRa delta and full update | PASS: signed SD delta and full-image transfer, installation and LoRa postboot checks |

## V4 WiFi OTA

The unchanged production `/update` page selected the ordinary shipping image
and started one native browser upload. Fresh USB CLI afterward reported the
full intended `dev-8b5660b0` version and EndF body hash `B93CB6D7775BC072`.
The 2559496-byte image SHA256 is
`0b37ec73fa39558d13e48213fe6c4ae365800c37811584bd93ea81aba1c2a8d7`.
The independent postboot/restoration phase passed with zero core errors,
unchanged normal radio/TX, original runtime flags, and strict Binary handback.
Its private summary SHA256 is
`75d0ccaad83de2ce6b928a5545a48c84c03fcaf29a1a84cd4ceb6f3a16e1444a`.

The browser observer reported a CDP command error after the upload action.
It did not retain an HTTP status/result-body proof. This is an observability
failure recorded separately from the installed-image proof; no HTTP 200 claim
is made. The unchanged firmware was not uploaded again solely to repeat that
measurement. An earlier preparation attempt used an obsolete WiFi status
parser and timed out; its verified restoration passed before the corrected
parser was used. Neither preparation attempt wrote firmware.

A known test admin password and the actual protected lab WiFi fixture were
intentionally configured and retained. Secret values and network/device
addresses are omitted. The Pi's network settings were unchanged.

## RAK3401 internal LoRa delta and gateway handback

The physical internal-flash delta completed all 9/9 blocks in 23 seconds.
The 80-second post-apply probe verified the exact intended ordinary shipping
EndF body hash `4748CB6ABFB3EBF4`. Normal-radio LoRa communication passed after
installation, and the source's original receive-power-saving setting was
restored. This application-only update transferred no bootloader or
SoftDevice payload.

The first gateway restoration guard failed when the initial `ver` command
returned `Unknown`; its other getters, intended image hash and zero core
errors were recorded separately. A second independent guard passed the complete
verification and restored the original gateway service. Exact serial-port
ownership and unchanged original service configuration were verified. The
first failed guard remains a failed workflow record, not a gateway pass.

The later application-only LoRa delta to commit `2bd4cb4d1` completed all
55/55 blocks in 103 seconds. An on-air install acknowledgement verified the
unsigned internal-flash delta, and on-air postboot reads proved exact body
`1A3C9EB603C581C3` after 80 seconds plus the full `dev-2bd4cb4d` version.
The receiving RAK used LoRa for setup, progress, installation and postboot
proof. No receiver USB command drove this update. Normal radio restoration
passed. Lost postboot status/version replies required bounded getter retries;
their failed attempts remain in the private log. A subsequent independent
USB diagnostic snapshot verified the same latest image, original saved
preferences and zero core errors before the CPU sleep measurement.

That first latest-image CPU measurement FAILED. Over 90.013 seconds, the
nonhalting MEM-AP capture recorded 8013 CPU states, with one sleeping state
(about 0.01% weighted sampled time). There was no halt, lockup or reset in
the capture. Firmware diagnostics reported zero sleep-wait calls and zero
eligible time; the surrounding diagnostic window was blocked primarily by
`usb.recovery`. The saved settings were CPU power saving on, USB logging on,
USB debug off, the system watchdog on and the USB logging watchdog in Auto.
The gateway service and UART were closed during the capture.

The watchdog's Auto policy still retained a previously confirmed reader and
an initial recovery stage after the serial client closed. The shared awake
hint treated that waiting policy as work requiring the CPU to remain awake.
A focused nRF52 fix and physical retest are recorded below. Logging,
watchdog settings and the failed result have not been disabled or cleared to
obtain a sleep pass. CPU debug enable was already set and stayed unchanged;
the explicit firmware sleep veto is recorded independently of that limit.
Subsequent authenticated LoRa reads returned the exact same latest body and
boot uptime, with zero core errors and both receive/transmit counters
advancing by three. Radio communication remained functional after the failed
idle measurement; this is not a CPU-sleep pass.

Commit [bd4524318](https://github.com/mikecarper/MeshCore/commit/bd4524318)
allows the nRF52 interrupt wait while USB watchdog policy timers run. Actual
transport recovery still vetoes sleep; logging, Auto/On mode and the existing
recovery/reset deadlines remain enabled. Other platforms retain their prior
sleep guard. The regression failed with the old predicate and passed with the
fix across the four role guards. All 31 relevant regression methods passed.
Blame places the earlier shared awake predicate in `3add4695cc` and
`18f7edcf82`; it is present in the older `8b5660b0` image as well as `2bd4cb4d`.
The rebuilt image passed physical confirmation below.

The fixed RAK3401 image was installed using another application-only LoRa
delta: 20/20 blocks in 71 seconds. The install reply was lost, so the install
command was not replayed. Exact on-air postboot body `15B81DD21FB8A906` and
the full `dev-bd452431` version proved the outcome after 30 seconds. Normal
radio restoration passed. Independent USB diagnostics afterward verified the
same image, unchanged saved preferences and zero core errors.

The fixed CPU retest PASSED. A 90.013-second nonhalting MEM-AP capture recorded
7989 states, including 6275 sleeping states: about **78.6% weighted sampled
time asleep**. There was no halt, lockup, step or reset during the capture.
Existing CPU debug enable stayed unchanged. This measures sampled CPU state,
not electrical current or exact sleep residency. The surrounding firmware
diagnostic window recorded 163516 sleep-wait calls and returns, zero errors,
zero pending-recovery vetoes and zero time blocked by `usb.recovery`.
Logging, CPU power saving, the system watchdog and the Auto USB logging
watchdog remained enabled. The capture occurred before the existing recovery
deadline; waiting for the watchdog to expire did not produce the pass.

After the capture, authenticated LoRa reads proved the same installed body
and boot, zero core errors and advancing receive/transmit counters (+4/+3).
The original diagnostic-enable setting was restored, and the original
gateway service resumed with its unchanged configuration and exact serial
port ownership verified. The additional diagnostic leases were released.

## RAK4631 and XIAO nRF52 full QSPI LoRa updates

The RAK4631 downloaded all 325/325 blocks in 375 seconds. Its install response
explicitly verified a full image on QSPI, and the post-apply probe found the
intended ordinary shipping EndF body hash `B0886153CE824448` after 30 seconds.
Normal radio settings were restored to 910.5250244 MHz, 62.5 kHz bandwidth,
SF7 and CR5 with TX at 2 dBm. The repeater role was retained. Fresh USB
postchecks reported zero core errors and identified the W25Q16 QSPI device
as JEDEC `EF4015`, with 2 MiB capacity. This qualifies external QSPI apply;
an internal-only RAK4631 hardware result is not claimed.

The XIAO nRF52 downloaded all 280/280 blocks in 258 seconds. Its install
response explicitly verified a full image on QSPI, and the post-apply probe
found the intended ordinary shipping EndF body hash `725FDE69F8C0B8EA` after
30 seconds. Normal radio settings were restored to the same frequency,
bandwidth, SF and CR with TX at 22 dBm, and the repeater role was retained.
Fresh USB postchecks reported zero core errors. The external Puya QSPI
device reported JEDEC `856015` and 2 MiB capacity.

After each application update, the first independent USB `ver` command
returned `Unknown`; a second independent read passed. The gateway showed
the same observation. All failed first-attempt records are retained. This
unresolved startup or CLI bootstrap observation is under investigation; it
is not treated as missing command support or a first-attempt pass. The
successful image, role, settings and core checks above describe the later
independent verification.

## Two-frequency ESP-NOW bridged one-hop LoRa update

The physical one-hop test PASSED. The V4 source ran `2bd4cb4d1` and the
RAK4631 received an application-only delta to `bd4524318`. Its setup,
discovery, download, progress checks, install command, postboot proof and
settings restoration all used LoRa. The receiving RAK's USB and Bluetooth
interfaces were never opened for this case.

The measured path was V4 at 909.5 MHz to a V3 bridge, ESP-NOW to a XIAO
ESP32 bridge, then LoRa at 908.5 MHz to the RAK4631. Both LoRa segments used
500 kHz bandwidth, SF7 and CR5. The two bridges copied received packets before
appending their own hop, with one-hop limits. Disabling the far bridge's
ESP-NOW link made the target's full-key query time out; re-enabling and
verifying the same configuration restored that query. This counterfactual
confirms that the two-frequency bridge was required.

The ordinary file-data session populated the source catalog and its automatic
discovery burst. No separate announcement command or control channel was
used. The first asynchronous catalog query requested discovery; the next
query found the intended manifest. Download completed **62/62 blocks**.
The one install command received an on-air acknowledgement verifying the
unsigned QSPI delta. Subsequent normal-channel LoRa reads proved exact
installed body `D2073EC88FF4E459`, the full `dev-bd452431` version and zero
core errors. Original target policies, receive power saving, output path and
the source's saved contact path were restored. The package SHA256 is
`f0a7319570394e23f06c9a901838be3cbaf5ae520d2743607828977e5fa3a0e9`.

A passive source USB capture wrote zero bytes to the radio and recorded
47 matching update requests with one hop through the measured near bridge.
This is source-side packet evidence, not an independent RF capture of the
whole chain. The separate frequencies, bridge counterfactual and on-air
install/postboot proofs establish the complete case. The integrated private
receipt SHA256 is
`c6d6b2e2d3aefec128303b0ef5e2d8a0be52c38f03bc17ecf3032f4118489cc6`.

Preparation failures remain recorded separately: a historical channel-busy
flag prompted one documented LoRa restart, and several bridge receive-power
configuration attempts returned a generic busy/unsupported rejection before
a fresh configuration check and acknowledged attempt succeeded. No cause
for those rejections or the historical busy flag is claimed fixed.

Both temporary ESP32 bridges were returned to Full Companion images built
from `ebb59d482`. Exact runtime bodies were `E297CF6E342C8332` (V3) and
`4EEB12667E5E554B` (XIAO ESP32), with matching Binary/CLI identity and zero
core errors. The V3's first postflash Binary handshake timed out; a later
independent read passed without a reset or another flash. Its role reply
required a narrow correction to the bench parser's nested prompt handling.
The XIAO's positive-readiness check also rejected a valid prompt-prefixed
acknowledgement before sending any Binary request. After correcting that
check, its first Binary handshake and complete CLI checks passed without
another flash, reset or settings change. Original failed workflow receipts
remain retained. These bench corrections are not claimed as firmware fixes.

## Findings and fixes

An authenticated nRF52 application handoff does not preserve a custom
peripheral Bluetooth address. The retained bond belongs to the central peer;
the bootloader can return at the peripheral's factory address. The first RAK
attempt looked only at the custom application address and sent no firmware.
A subsequent fresh authenticated handoff found the expected bootloader at its
previously USB-bound factory address and passed live model, manufacturer,
firmware and DFU revision checks before starting data transfer.

The host LoRa updater forced old fixed in-place workspace limits despite the
images carrying hash-bound layout records. MeshCore commit
[8e96b4d3b](https://github.com/mikecarper/MeshCore/commit/8e96b4d3b)
passes an explicit workspace only when requested, allowing motatool to size
and validate the recorded application/staging layout. Legacy images retain
the tool's conservative fallback. The focused file passed 318 host tests,
including real-tool coverage for larger internal images, external layouts,
explicit bounds rejection and legacy rejection. Package preparation alone
does not qualify hardware apply.

The first RAK3401 LoRa attempt stopped during preflight because deployed
adaptive-storage images omitted the bootloader ABI and codec mask from
`ota self`. It changed neither firmware nor temporary radio settings.
Commit [4b2f37013](https://github.com/mikecarper/MeshCore/commit/4b2f37013)
adds those actual fields before the adaptive storage diagnostics. For existing
images, the host runner verifies the known adaptive reporting contract with
the installed bootloader's complete read-only status, including its
board/name/target identity, CRC status and storage profile. That contract
guarantees application codec subset `0x5`; storage flags are not treated as
codecs. Bootloader packages still require directly reported capability fields.

The updater host suite passed 365 tests with zero skips, and all seven
firmware diagnostic/policy host tests passed. The affected RAK3401 canonical
Full/Reduced build pair passed, reporting 619832/567640 bytes of flash use.
An earlier build compiled successfully but its packaging guard rejected
concurrent host-source changes; the second build completed packaging from a
frozen workspace. The modified adaptive branch is preprocessed out of
source-only Full Companion builds. These build results do not change the
`8b5660b0` hardware-artifact binding above.

Commit [4c898ecbc](https://github.com/mikecarper/MeshCore/commit/4c898ecbc)
recognizes native DEFLATE logical-block progress in the source's passive
status output. It uses that output only as a progress signal, not as proof
that the receiver has completed or installed an image. The host updater
suite passed 369 tests with zero skips after this change.

Commit [720b9728c](https://github.com/mikecarper/MeshCore/commit/720b9728c)
adds cold-idle RAK host-preflight preparation. The preparation may initialize
optional staging media, but does not itself download firmware, install an
image or change saved preferences. The host updater suite passed 379 tests
with zero skips. The targeted live cold-idle RAK4631 check subsequently
passed: one USB restart established the unchanged, idle application with
unprobed storage, then authenticated LoRa reads observed that state and the
host performed exactly one explicit storage-preparation query. The result
was external QSPI with ABI 3 and codec subset `0x5`, with unchanged body
`B0886153CE824448` and no firmware download or bootloader write. The first
host attempt lost a version reply before preparing storage; a fresh read-only
snapshot and bounded getter retries completed the check without another
restart. Both attempt records are retained.

Commit [093fd98a3](https://github.com/mikecarper/MeshCore/commit/093fd98a3)
retries lost remote clock reads within the existing bounded operation budget.
Validation passed 671 tests, including nine new clock-read regressions; one
optional PyPI integration test was skipped. Canonical Full and Reduced
RAK4631 and RAK3401 pairs, plus Full V3 and XIAO S3 WIO images, built
successfully from this commit. The ESP32 images were subsequently installed
as the temporary one-hop bridges. Build success alone does not qualify an
update or replace the earlier hardware results.

Repeater Bluetooth provides an update service; Companion terminal/sync
functionality is not claimed for repeater builds. The RAK4631 reports a 2 MiB
W25Q16 QSPI device and completed its full QSPI LoRa update as recorded above.
RAK3401 live diagnostics report no external NOR and 252 KiB
internal staging capacity, matching the completed internal delta case.

Commit [2bd4cb4d1](https://github.com/mikecarper/MeshCore/commit/2bd4cb4d1)
automatically restarts the existing four-beacon discovery burst when a
complete, changed update catalog becomes available through the source's
ordinary file-data session. It requires no separate announcement command or
control channel. USB or WiFi can feed files into the source radio; receiving
radios still discover and download them over LoRa. All 136 affected native
test methods passed, including cold catalog discovery and a negative control
that removes the production readiness trigger. Canonical V4 Full and RAK3401
and RAK4631 Full/Reduced builds passed. This fixes source discovery, and does
not establish a fix for the separate Tower manifest timeout.

The V4 source subsequently accepted one application-only WiFi upload of this
commit. Authenticated GET and POST both returned HTTP 200, followed by exact
USB version/body proof (`B6E8C347E1C5FA69`) and unchanged saved preferences
and receive-power-saving configuration. This deploys the source firmware;
it is not a receiver LoRa qualification result. The initial preparation
rejected a valid start acknowledgement with a WebConfig-status suffix before
any upload; the corrected continuation did not replay the start command.

During RAK4631 discovery, source receive power saving was on and discovery
timed out. After disabling that setting under a restoration intent, a fresh
advert was received. This sequence records an observation; it does not
establish a receive-power-saving firmware defect. Source receive power
saving stayed off under the owned restoration intent while the remaining
LoRa cases ran. Exact final source restoration is recorded below.

## MeshTower signed SD updates and remaining failures

Before the MeshTower OTA cases, its unchanged earlier application had a
latched core error bitmask `0x02` while still receiving. This bit records a
generic channel-busy wait exceeding four seconds. It is a historical flag,
not a count of two errors or evidence that the radio is currently stuck.
Diagnostics were retained. One software restart cleared the bitmask to zero,
observed at 39 seconds uptime. Its normal radio settings and 0 dBm TX were
unchanged, and the earlier application's EndF body remained
`60EE4D4C61CFCA58`. A later historical channel-busy flag was recorded again
after that restart. No underlying channel-busy defect is claimed fixed,
and a low ADC battery reading is not identified as the cause.

The MeshTower temporary-channel rehearsal at SF5 and 500 kHz bandwidth
failed three full-public-key proof attempts before any firmware transfer.
Natural lease expiry and return to the normal channel were independently
verified. A retry at SF7 and 500 kHz bandwidth passed full-public-key,
status and `ota self` proofs on the temporary channel. The SF5 preflight
failure remains unresolved; no firmware was transferred in that attempt.

The signed MeshTower delta update then completed all 41/41 blocks in
206 seconds using SF7 and 500 kHz bandwidth. The install acknowledgement
verified a trusted signature and a delta image on SD. The post-apply probe
verified EndF body hash `F1909AD4C46915FD` after 70 seconds and a fresh
OTA-check version built from `8b5660b0`. Return to the normal radio was
verified.

The first signed full-image attempt stopped before TempRadio when the host
observed a zero clock epoch; it transferred no firmware. The bounded
clock-read retry fix above addresses the host's handling of lost reads.
A second full-image attempt at SF7 and 500 kHz bandwidth passed the full-key
and status proofs, but all three `ota self` proof attempts failed. Safe
temporary-lease expiry and return to the normal radio were verified. No
firmware was transferred in either of those full-image attempts; full apply
and postchecks were still pending at that point.

A local USB snapshot afterward confirmed body `F1909AD4C46915FD`, 1133 seconds
uptime, core error bitmask `0x02` and an empty queue. Radio diagnostics
reported RSSI -60 dBm, SNR 11.25 dB and noise -103 dBm. These values do not
establish why the remote self proofs failed. A separate USB diagnostic
attempt failed on open with error 71 before any getters. The Pi's DWC USB
controller then re-enumerated the same Tower while application uptime
remained at 1133 seconds. This is a separate host transport failure, without
evidence of an application reboot or a basis for a brownout claim.

A read-only comparison of the earlier C46 and pinned `8b5660b0` handlers
did not support the proposed clock or access-control explanation for the
rehearsal failure. The relevant handlers were the same; no clock or ACL
cause is claimed from this review.

A later local-control diagnostic made the signed full catalog visible, but
both matching pull attempts remained at manifest timeout, 0/0 blocks. No
install was requested. This local-control attempt is not a wireless-only
qualification pass. Its temporary radio and saved receive-power-saving
settings were restored and its USB port closed. One restoration command was
explicitly rejected with a misleading "unsupported" response; source review
shows that this response also covers a busy or failed reconfiguration. A
fresh identity/settings check followed by one new, acknowledged restoration
attempt proved the original configuration. No particular runtime guard is
identified as the cause of that rejection.

A later signed-full retry used the ordinary production file-data session and
source catalog readiness, with every receiver command on LoRa. Its first
attempt stopped before new data because an old failed receive session
required an explicit replacement choice. The one-minute temporary-channel
cleanup command lost its acknowledgement. The updater then proved identity
on the temporary channel and restored the source, but did not prove that the
receiver had returned to its normal channel. The next attempt could not
reach the receiver on the normal channel. These are failed workflow records.

A bounded, LoRa-only recovery found the exact Tower still running body
`F1909AD4C46915FD` on the temporary channel. One command restored its normal
radio; its acknowledgement was lost and the command was not replayed.
Subsequent authenticated normal-channel reads proved the full identity,
unchanged body, inactive temporary mode, normal radio and 0 dBm TX. No target
USB, Bluetooth, reset or flash operation was used. A historical core bitmask
`0x06` was retained: channel-busy timeout and radio outside receive for over
eight seconds. It is a bitmask, not a count of six errors. The recovery receipt
SHA256 is
`bc44880091e0024966fb6b2d9fd77b21556a9899e9c9995cf772dc14ae1bd57e`.

After that recovery, a fresh ordinary updater attempt passed its temporary
channel rehearsal and natural return, explicitly replaced only the old failed
receive session, and downloaded the signed full image **279/279 blocks in
831 seconds**. The install acknowledgement verified a trusted signer and a
full image on SD. Normal-channel LoRa postboot reads proved body
`718365A6E08823C7`, bootloader apply OK and the full `dev-ebb59d48` version.
The first matching body response arrived during the 60-second postboot probe.
A lost optional statistics reply required a bounded getter retry. The
570682-byte package SHA256 is
`4f92525f7500ad74b7f1895a62c4626a02a049b1a3978906ae8eea8617393bde`.
The production runner exited successfully; its private result SHA256 is
`de1bb4c4fa7af7fe627c00d96c94d1f7244141556c29271754379ad8f7fd7ca9`.
All receiver setup, download, install and postboot commands used LoRa; its USB
and Bluetooth interfaces were never opened for this attempt. The source was
fed through its ordinary file-data session, with no extra announcement or
separate receiver control channel.

An independent, authenticated LoRa postcheck then verified the new full body
and version, repeater role, normal radio/TX, inactive temporary mode, zero
core error bitmask and an empty transmit queue. It removed only the owned
fourth test signing key and verified that the original three key prefixes
remained in their original order. The CLI exposes prefixes, so this is not
an independent full-byte readback of those three keys. The postcheck repeated
the identity, radio and core checks after removal and closed its controller.
Lost getter/status replies used bounded read-only retries; all failed attempts
remain recorded. Its private summary SHA256 is
`02964ab9a2f511f96055ef6c99c59d32bb091d21dbf5c61dbe9de5ac00555659`.

The passive source-only capture recorded 405398 bytes and wrote zero USB
bytes. Its SHA256 is
`6558971dea7e9cdc221e3e196d34f5ae00427300932c766e3fb7798d3332d194`.
The capture was stopped and its serial port closed before the source's
original logging-off setting was restored and verified. This capture is
source-side evidence; the receiver's installed-image and runtime proofs
above came from LoRa.

The host cleanup defect is separate from the radio transfer: temporary-channel
identity alone cannot establish that a lost relative-lease command executed.
Cleanup must retain its recovery obligation until a full-key proof and
inactive temporary mode are observed on the normal channel. The same
requirement applies independently to controlled relay participants.

Commit [c5c67f8f7](https://github.com/mikecarper/MeshCore/commit/c5c67f8f7)
fixes that host ownership defect. It persists a private recovery record for
each full-key-bound target and controlled relay before arming, records a
one-shot shortening attempt before sending, and requires each participant's
full identity plus inactive temporary mode on the normal channel before
retiring its obligation. A shared Full Companion source must also report its
actual temporary mode inactive; its saved Binary radio settings alone are
insufficient. Lost relative-lease acknowledgements are not replayed. Unresolved
records survive interruption without passwords, and manual read-only recovery
is documented in the [LoRa OTA automation guide](../lora_ota_automation.md).
The regression cases cover delivered and undelivered lost acknowledgements,
independent relay failures, mismatched keys, active temporary profiles,
interruptions, existing recovery records, resolved-password redaction and the
explicit no-install staging path. These are host changes; accepted unchanged
firmware was not flashed again to validate them.

## Final source restoration and handback

After all transfers and the Tower signing-key cleanup, two fresh USB cleanup
attempts received an explicit `Error: radio busy; retry` while restoring the
source's original RXPS setting. Both attempts stopped and retained their raw
failed records. This firmware rejects that command before updating or saving
RXPS preferences; a missing or ambiguous reply would not permit the same
continuation. Fresh read-only diagnostics showed normal receive operation,
zero core errors, an empty queue and RXPS still off. They did not identify
which radio reconfiguration guard rejected those particular commands.

A bounded continuation used the production updater's varying retry cadence
for this exact explicit busy response, opening a fresh console after each
rejection. Its second attempt received the exact positive acknowledgement
and exact original configuration readback: on, level 8, preamble 16,
39657 microseconds receive and 15975 microseconds sleep. It did not retry a
lost or malformed acknowledgement, reset the radio or change firmware.
The continuation receipt SHA256 is
`4253c91dbf2eca91e7b2716367e27e95a7dd1b952008b9ef6bb036fd673d3c62`.

A separate final cleanup skipped the already restored RXPS setting, restored
all five original saved flags, and verified normal radio/TX, idle detached OTA
file service, original hop settings and strict USB Binary handback. It disabled
the test WiFi runtime before restoring MQTT. The completed private summary
SHA256 is
`1c07fc8301f883eb3a33201924ca77ce4d2d02573b9a27a785f84547a06a8165`.
The hash-bound completed receipt retired the host's RXPS restoration intent.
Owned test tunnels, target leases and the cold-idle hold were closed; the
root hardware session had no remaining FLOCK descriptors before it exited.
The already restored RAK3401 gateway service was left running.

## Limits and completion

The listed physical OTA cases and their restoration are complete: V4 WiFi,
RAK3401 internal delta, RAK4631 and XIAO nRF52 external QSPI full images,
Tower signed SD delta/full, and the two-frequency ESP-NOW bridged one-hop
update. Latest RAK3401 CPU sleep, post-idle LoRa and gateway handback passed.
Each case records its exact firmware commit and body; these results do not
qualify all 13 radios against every later commit.

Receiver setup, progress, installation and post-install verification in the
new radio campaign used LoRa. Receiver USB commands did not substitute for
failed radio communication. Earlier local-control diagnostics remain
explicitly identified. The RAK3401's pre-fix historical channel-busy bitmask
`0x02` was retained without clearing statistics or claiming a sleep result
from that snapshot.

The first-command USB bootstrap observation, Tower SF5 preflight failure,
earlier full-image self-proof failures, separate USB open failure and
historical radio-busy flags remain unexplained. Later full-image transfer and
postchecks passed under the stated conditions; this does not establish their
underlying causes. Source restoration's explicit busy replies were handled
with bounded retries; no radio guard defect is claimed fixed by that action.
Private raw responses, keys, PINs and device identities stay outside the repo.
Earlier accepted Companion tests are not repeated without a relevant change.
