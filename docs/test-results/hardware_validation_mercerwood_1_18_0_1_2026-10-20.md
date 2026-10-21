<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_mercerwood_1_18_0_1_2026-10-20/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Mercerwood bench qualification: 12 active radios, 20 October 2026

Status: **PASS**. 12/12 active boards have complete
accepted bench coverage; 0 have a latest required failure and
0 remain incomplete. The original inventory has thirteen
radios: eleven Full Companions and two Full OTA repeaters. The active target
is twelve radios: ten Companions and two repeaters. MeshPocket is
operator-excluded from all further testing for separate bootloader work.

All thirteen 0865 candidate builds passed. Companion updates target
`08650f644b680a5dfaacb95142e3cef8529da9d2`; the table records each board's
actual installed application. Both repeaters retain actual
`c46defaefd642973cbbdb473815d56b5b261cb2e` (C46). Test-only commit
`190064f4b5fa97e75dcfca7876568b757ba43b31` passed
[all twelve CI jobs](https://github.com/mikecarper/MeshCore/actions/runs/39493222360).
Build manifest SHA-256:
`1dbf13ae8a3419f2c8e12d0432c37fa990d5bcfbb5649ab4d1d4ed4cec21a468`.
Seven active nRF52 boards retain the source
`88d39510140ce6894cf8e74b93cbd28d7387fa21` bootloader baseline; Companion
application-only updates transferred no bootloader or SoftDevice data.

That bootloader baseline describes this campaign's measurements. A subsequent
independent deployment restored the original applications after installing an
unpublished test bootloader on eight nRF52 boards. Its remaining USB stress
and RAK data-preservation limits are recorded in the
[known-failure follow-up](hardware_validation_known_failures_1_18_0_1_2026-10-20.md).
This does not repeat or extend the source-bound qualifications below.

| Board | Installed source | Required USB / BLE / RF / contacts | Overall |
| --- | --- | --- | --- |
| Heltec V4.3, FEM off | 0865 | USB/BLE/contacts PASS; RF retained ABF | PASS |
| RAK 4631 | 0865 | USB/BLE/RF/contacts PASS | PASS |
| Seeed XIAO nRF52 | 0865 | USB/BLE/RF/contacts PASS | PASS |
| Seeed T1000-E | 0865 | USB/BLE/RF/contacts PASS | PASS |
| Heltec V3 | 0865 | USB/BLE/RF retained ABF; new contacts PASS | PASS |
| RAK WisMesh Tag | 0865 | USB/BLE/RF retained ABF; new contacts PASS | PASS |
| Heltec T096, FEM on | 0865 | USB/BLE/RF retained ABF; new contacts PASS | PASS |
| Heltec MeshPocket | Current state unverified | Historical PASS as of 22:28 UTC only; excluded from active target | Operator-excluded |
| LilyGo T-Deck | 0865 | USB/RF/contacts PASS; BLE PASS with WiFi quiet | PASS |
| Seeed XIAO ESP32-S3 | 0865 | USB/RF/contacts PASS; BLE PASS with WiFi quiet | PASS |
| SenseCAP Indicator | 0865 | USB/BLE/RF/contacts PASS | PASS |
| Heltec MeshTower V2 SD | C46 | USB10/3, warm restart and RF3 PASS; SD PASS (read-only metadata) | PASS |
| RAK 3401 MQTT gateway | C46 | USB10/3 retained C46; new warm/RF3 PASS; service PASS | PASS |

The [safe evidence summary](hardware_validation_mercerwood_1_18_0_1_2026-10-20.safe.json)
records each axis's actual tested source, artifact, measurement interval,
conditions and evidence digest. V3, Tag and T096 retain valid ABF USB/BLE/RF measurements; V4 retains ABF RF.
Pocket's earlier ABF and 0865 results appear only in its excluded historical
record; its current installed application and bootloader are unverified
outside this report for operator bootloader work, and no further Pocket tests
are planned. ABF is
`abf7ba5d5c3958580d52d6954d816c08a035a552`. For active boards, changed applications, current identities and new 64/32
contact trials are separate measurements.
Reviewed source assurance `577aee5162c7553f58bf13b550560da50bbf73860ab37febe3674a5ae73c01aa`
covers the unchanged behavior; retained results keep their original source,
artifact and time. Binary equality and remeasurement are not implied.

Companion USB checks cover 100 query cycles, ten reopens, owned CRUD,
persistence through warm restart and applicable radio2 checks. BLE covers
three authenticated thirty-second sessions, exact USB-bound identity and
device information, clean core state and strict controller lifecycle.
Two-way RF verifies exact zero-hop DEV datagrams, counters and owned
channel/radio-lease cleanup. Each contact trial verifies 64 owned full-stream
records and a 32-record timestamp subset, then removes them and proves
absence after reopen while preserving unrelated records. Repeater coverage
uses ten query cycles, three reopens, verified warm restart and three
nonce-bound RF rounds. Gateway retains its earlier C46 query/reopen baseline;
its new held warm restart and RF rounds keep separate intervals and evidence
digests. SD coverage is read-only metadata, not media integrity.

T1000-E's eleven physical USB-priority phases passed.
These qualify the USB-priority policy, not simultaneous active USB/BLE.
The first current cold-host-release strict failure remains recorded before
one later explicit unchanged-firmware retest passed. XIAO nRF52's original
unaligned QSPI failure was corrected by shared buffer-alignment fix
`714cfc4546ac43c220d06abff9adb128f58d16dd`; its earlier strict BLE 0x3E
failure also remains recorded before the later clean same-bond result.

T-Deck and XIAO ESP32-S3 later passed strict three-session BLE with USB
connected and host WiFi quiet; earlier extra-0x3E failures remain in the
history. WiFi was checked at trial boundaries, not continuously. T-Deck's
initial two WiFi-on failures predate its current boot, so the observations
do not isolate WiFi from boot/current-PIN/state differences. Its diagnostic
wrapper retained a restoration-check FAIL; later read-only records separately
verified handback. XIAO's original wrapper passed handback. Separate exact
64/32 contact trials, secure controller proofs and cleanups later passed
with normal WiFi restored. WiFi association at 2437 MHz was observed before
and after those trials.
No WiFi root cause or firmware fix is established.

V4's earlier contact setup refusal preceded a later bounded-transition
trial and exact cleanup. Tower's CAD2 history and Pocket's pre-DFU core8
refusal remain recorded before their separate warm preparations; preparations
are not qualification passes. Tower's cumulative receive/read-error count
does not prove CRC failure. Gateway's earlier warm failure had 43 complete
responsive snapshots with advancing uptime, not a proven hang. Its later
CAD2 baseline refusal came after the service was stopped. A separate
one-request warm preparation preceded the qualification's own warm restart
and RF3; the exact service/configuration owner then returned. Latest
accepted results do not relabel those failed attempts.

These finite checks do not establish RF range, phone interoperability,
long-duration reliability or every firmware feature. Earlier source-bound
results remain in the [fleet follow-up](companion_qualification_followup_2026-10-19.md),
[diagnosis follow-up](companion_qualification_f807_followup_2026-10-19.md), and
[initial USB-priority report](t1000_usb_bluetooth_priority_2026-10-20.md).
