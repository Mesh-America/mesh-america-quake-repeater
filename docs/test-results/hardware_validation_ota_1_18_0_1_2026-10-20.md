# OTA hardware qualification, 20-21 October 2026 UTC

Status: IN PROGRESS. Results below describe completed measurements only.
The operator authorized erasing these test nodes without backups. MeshPocket
remains excluded. No bootloader or SoftDevice payload is part of this campaign.

Completed hardware OTA results use artifacts pinned to
`8b5660b00b88d8abaae094859bc1232f7ce886fd`.
That commit changes documentation only relative to firmware source
`0b207a1ec3a32eb0a8ad6b8643db211de4921cd4`. Separate OTA-check version strings
produce distinct image hashes for controlled update tests. The common numeric
version is `0x01120001`; same-version updates are explicitly authorized for
these tests. They are not claimed as numeric version upgrades.

| Device and role | Transport | Result |
| --- | --- | --- |
| Heltec V4.3 Full Companion | Production browser WiFi OTA | PASS: one upload installed the exact intended image; postboot identity, version, core, radio and original flags verified |
| RAK4631 unified repeater | Bluetooth application DFU; QSPI full LoRa OTA | Transfers and eventual postchecks PASS; initial USB version response remains under investigation |
| Seeed XIAO nRF52 repeater | Bluetooth application DFU; external QSPI full LoRa OTA | Transfers and eventual postchecks PASS; initial USB version response remains under investigation |
| RAK3401 unified repeater and gateway | Bluetooth application DFU; internal LoRa delta; gateway restoration | PASS: Bluetooth update and repeater service, internal LoRa delta apply, normal-radio restoration and gateway service handback |
| MeshTower SD repeater | Signed SD-backed LoRa delta and full update | Delta transfer, signature verification and postboot checks PASS; full update pending |

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
A focused nRF52 fix and a new physical measurement are in progress. Logging,
watchdog settings and the failed result have not been disabled or cleared to
obtain a sleep pass. CPU debug enable was already set and stayed unchanged;
the explicit firmware sleep veto is recorded independently of that limit.
Subsequent authenticated LoRa reads returned the exact same latest body and
boot uptime, with zero core errors and both receive/transmit counters
advancing by three. Radio communication remained functional after the failed
idle measurement; this is not a CPU-sleep pass.

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
successfully from this commit. These newly built images have not yet been
flashed; their build success does not replace the earlier hardware results.

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
saving remains off under the owned restoration intent while the remaining
LoRa cases run; final source restoration is pending.

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
firmware was transferred in either full-image attempt; full apply and
postchecks remain pending.

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

## Limits and completion

The MeshTower signed full-image LoRa case and final source cleanup remain
pending. The live cold-idle RAK preflight check is complete. Newly requested
two-frequency ESP-NOW bridged one-hop OTA testing and latest RAK3401 CPU
testing also remain pending. Receiver update setup, progress, installation
and post-install verification in the new radio campaign must use LoRa;
receiver USB commands cannot substitute for failed radio communication.
The RAK3401's current-image pause snapshot recorded historical channel-busy
bitmask `0x02`; it was retained without clearing statistics or claiming a
CPU-sleep result. The first-command USB bootstrap observation,
Tower SF5 preflight failure, later full-image self-proof failures and separate
USB open failure remain unresolved. The Tower signed delta, RAK4631 and XIAO
nRF52 full QSPI LoRa updates and their later postchecks are complete; the
RAK3401 gateway handback is complete for the earlier pinned image.
Private raw responses, keys, PINs and device identities stay outside the repo.
Earlier accepted Companion tests are not repeated without a relevant change.
