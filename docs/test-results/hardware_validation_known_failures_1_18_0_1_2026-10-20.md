<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_known_failures_1_18_0_1_2026-10-20/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Known-failure follow-up, 20-21 October 2026 UTC

Status: **V4 USB PASS**; Morse false letters are an accepted limitation.
Final-source CI remains in progress. This scoped follow-up preserves failed
measurements and the operator's limited Morse acceptance. It does not grant broader release approval. The current V4 is a
different physical board from the 18 October campaign.

Final source: `0b207a1ec3a32eb0a8ad6b8643db211de4921cd4`.
[Safe evidence summary](hardware_validation_known_failures_1_18_0_1_2026-10-20.safe.json)
records source bindings, evidence digests and explicit pending fields.

## Builds and host verification

| Check | Source | Result |
| --- | --- | --- |
| RAK4631 Full | `0b207a1ec` | PASS: 712432/712704 application bytes, 272 bytes free |
| T096 Full, FEM on | `0b207a1ec` | Shipping build/package PASS |
| V4.3 Full, FEM off | `0b207a1ec` | Shipping build/package PASS: 2559496 application bytes |
| Focused Morse host suite | `0b207a1ec` | 111 methods PASS |
| Targeted USB host suite | `7278eacb9`, included in final source | 45 methods PASS, including 12 HWCDC TX backport suite methods with actual ISR scenarios |
| Earlier unchanged RadioProfile suite | `fc72943f3` | 17 methods PASS; not rerun for final source |

RAK Full retains all 13 feature capabilities plus `profile.full`; its build
used INA260 1.5.4 and MLX90614 2.1.7. Builds and host tests do not qualify RF
behavior or physical USB stability. In
[CI run 39523154379](https://github.com/mikecarper/MeshCore/actions/runs/39523154379),
all 11 non-main jobs are reported green; the main host job is **PENDING**.
A completed workflow pass is not yet claimed.

## V4 application and native USB

The earlier `4773ac4219666d0f5b4c2bff5eb72aa053014662` application passed full
readback with unchanged partition table and OTA metadata. An initial private
adapter's ordinary hard reset left native S3 in forced download mode despite
correct readback. The pinned flasher's masked forced-download clear and
watchdog reset restored the application. Its adapter guidance was clarified in
meshfirmware commit [4ce4f44](https://github.com/mikecarper/meshfirmware/commit/4ce4f44);
the flasher already had the correct sequence.

The second logging-on native-console trial on `4773ac42` passed 600.1086
seconds with zero idle command writes. The observed idle phase started at
2026-10-21 00:13:03.667 UTC. First reply/reopen took 124/21.8 ms; uptime advanced
378 -> 979 -> 981 seconds. Identity, settings restoration, strict binary handback
and cleanup passed, with zero core errors. However, watchdog recoveries rose
from 0 to 2; the last reason was client inactivity (`0x08`). This is a transport
PASS, not a clean watchdog qualification. The earlier browser startup failure
and its successful restoration remain recorded separately.

Fix `7278eacb9131d613da719fee814fefcdad3adf23`, included in final source,
requires 100 ms of continuous presence loss before invalidating the valid
client lease and recognizes the host-backed physical reader. It preserves
bus-reset, stall and true-unplug recovery. The finding does not conclusively
attribute both earlier events to that path.

Ordinary shipping `0b207a1ec` was restored successfully at
2026-10-21 01:21:32 UTC. All 2559496 application bytes matched SHA256
`04eed20ee0f964fef2a5a0f74f4aafe4b11e0a71b011ff757efc96c03a2cfb14`;
partition table and OTA metadata stayed unchanged. Runtime source/identity,
absence of the raw diagnostic marker, strict binary handback and clean core
state passed. This was an application-only update.

Final logging-on native-console case 3 on this shipping image: **PASS**.
The idle lasted 600.0913 seconds with zero command writes; post-idle reply and
reopen took 105.3/20.5 ms. Uptime advanced 172 -> 773 -> 775 seconds, with
zero core errors. Watchdog recoveries stayed 2 -> 2 and boot count 0 -> 0.
The watchdog's `boot` field counts reset authorizations, not all physical boots;
the continuous uptime separately establishes no MCU restart during this case.
Identity, original preferences, strict binary handback, TTY restoration and
owned browser/stream cleanup passed. The wrapper finished at
2026-10-21 01:34:33 UTC without errors. This qualifies the current board and
artifact for this finite logging-on idle/reopen case; it does not establish
the cause of the different 18 October board's USB disappearance.

## Morse measurements and accepted limitation

These shipping controls use automatic detection without HIL threshold overrides.

| No intentional TX, 30 seconds | RAK4631 | T096 |
| --- | --- | --- |
| Unchanged `08650f64` | FAIL: 3 false characters | FAIL: 1 false character |
| Adaptive `4773ac42` | PASS: 0 characters in this control | UNQUALIFIED: 6 retained characters and command timeout during external-actor contention |

The contended T096 observation is not a clean detector pass/failure attribution.
The RAK control alone does not qualify complete messages or other board families.

An unchanged `08650f64` V3 transmitted to a shipping `4773ac42` V4. The quiet
control came first: **FAIL**, 26 false characters in 300.820761 seconds.
Three messages at 25/60 WPM, two repeats, then produced **4/12 exact passes and
8 failures**. Both preferences and strict binary handbacks passed; the wrapper
reported no errors. This one-way campaign does not replace the original two-way
24-message matrix.

The operator accepted false letters for now and stopped further detector/gate
work. That accepts the false-letter limitation; it does not establish complete
message accuracy or turn the failed measurements into passes. Further Morse
experiments are not a mandatory gate in this follow-up. The receive setting
minimum is 15 WPM, default 25; TX at 1-14 WPM remains available. Hand-timing
tolerance remains, so setting validation is not an absolute physical speed cutoff.

Separate raw diagnostic captures used production RF settings and automatic
squelch. Capture integrity, both preference restorations and both strict binary
handbacks passed. These instrumented captures do not qualify shipping accuracy.
The ordinary shipping image is restored; raw lab details remain private.

## External nRF52 bootloader handback

The operator reported completion of their separate bootloader testing. Its
deployment record was also read: **COMPLETE_WITH_KNOWN_LIMITATIONS**, eight live
INFO/original-application handoff proofs and gateway service handback PASS.
It uses unpublished test bootloader `TEST_0x02040B7E`, source
`b07255d4cdc601f1313e4cbe020caad3b5544821`, not a latest-stable release.
The record reports no publication or push by that deployment.

Limits remain: scheduled concurrent USB control failed with one EPIPE and 31
successful requests; 11 unique bulk halt-clear cycles passed. RAK secondary-data
preservation is uncertain after earlier manual scratch overlap. Identity and
seven settings match, without a complete immediately prior contact/channel
baseline. These records do not qualify final-source `0b207a1ec` applications.
The nRF52 hold is released; no new nRF52 campaign was started. MeshPocket remains
excluded from all further testing in this session.

## Remaining scope

Current CI completion and final release artifact-matrix binding remain pending.
The scoped V4 logging-on hardware case is complete. The [20 October fleet qualification](hardware_validation_mercerwood_1_18_0_1_2026-10-20.md)
retains its accepted USB/BLE/RF/contact coverage at its actual sources and
conditions. This report neither reopens those closures nor extends them to
unmeasured artifacts. Historical failures in the
[18 October report](hardware_validation_mercerwood_1_18_0_1_2026-10-18.md)
remain visible. Private device identities, addresses and raw responses are omitted.
