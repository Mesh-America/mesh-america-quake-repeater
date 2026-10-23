<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/rak_release_fixes_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# RAK release fixes and targeted hardware checks, 22 October 2026

Status: **RAK4631 Full/Reduced Repeater builds and physical radio checks PASS;
RAK3401 Full Room Server radio, CPU sleep and health checks PASS.**
All six selected RAK release packages passed their existing capacity,
capability, Bluetooth DFU and packaging gates.

Firmware and hardware results are bound to
[`adb11e7b4`](https://github.com/mikecarper/MeshCore/commit/adb11e7b41f2d3c561bc6aba4ebf6c92a45623bd).
The later `302e441e2` changes only Mini-selected CLI messages; selecting the
non-Mini branches reproduces the prior RAK source byte for byte. Unchanged RAK
checks were retained. The [machine-readable receipt](rak_release_fixes_2026-10-22.safe.json)
includes package hashes, RAM requirements, radio counters and CPU observations.

## RAM repair

The fresh starting source, `e34e83e6b`, failed both RAK4631 Repeater profiles:
Full had 81,668 internal bytes available against 85,152 required; Reduced had
84,680 against 85,152. These are separate from the earlier Full Companion
flash repair.

Repeater rule targets cannot contain both a scope and a region. One tagged
32-byte name replaces their two separate names, reducing each actual rule
from 332 to 300 bytes. All 63 slots remain, saving 2,016 allocated heap bytes.
FPF6/7/8 file formats retain their existing field widths and validation.

Ordinary nRF52 SSD1306 builds now use the existing source-enforced 2 KiB
allocation bound for this same concrete driver, correcting its previous
4 KiB estimate. This is a 2,048-byte accounting correction, distinct from
the rule-table saving. Stacks, packet pools, allocator/transient reserves,
sensor features and admission boundaries remain unchanged.

| Target/profile | Available internal bytes | Required heap bytes | Margin | Result |
| --- | ---: | ---: | ---: | --- |
| RAK4631 Repeater Full | 81,676 | 81,088 | 588 | PASS |
| RAK4631 Repeater Reduced | 84,680 | 81,088 | 3,592 | PASS |
| RAK3401 Room Server Full | 153,940 | 58,416 | 95,524 | PASS |
| RAK3401 Room Server Reduced | 156,928 | 58,416 | 98,512 | PASS |
| RAK3401 unified Repeater Full | 78,364 | 74,176 | 4,188 | PASS |
| RAK3401 unified Repeater Reduced | 81,368 | 74,176 | 7,192 | PASS |

These are canonical `build.sh build-firmware` Full/Reduced pairs with Cascade
settings, `--radio-preset usa-cascade-fixed` and `--require-ota`. The canonical
RAK4631 Repeater and Room Server packages retain their normalized internal-OTA
target identities. PlatformIO commands ran sequentially.

## Channel-busy repair

A proven dispatcher defect retained a profile's channel-busy timestamp after
its last waiting packet was cancelled or retired. A later unrelated packet
could inherit the old age and immediately force a transmit with error `0x02`.

New work now retires an unused wait before joining that profile. Queued work,
retained driver retries and foreign/direct-OTA owners preserve their live
backoff. `begin()` resets previous CAD state. No RAM fields or idle-loop scans
were added. Genuine sustained contention still raises the original timeout.

The original failed Room Server capture lacked enough RF data to prove this
was its cause. Both old installed repeaters also had latched `0x02` flags.
The new software regressions and finite new-image hardware results are the
evidence for this repair; historical failures remain recorded.

## Physical results

Application-only DFU installed the source-bound images on the Mercerwood Pi.
USB reopen checks confirmed role, version, EndF body identity and continuous
uptime. No chip/data erase, filesystem backup, bootloader or SoftDevice update occurred.

The RAK Tag was the independent LoRa witness. Each case used three fresh
eight-byte nonces, exact routed trace replies and advancing target RX/TX
counters. USB carried commands and observations; the request and reply crossed
the physical radio link. Settings were 917 MHz, SF7, BW62.5, CR5, preamble32,
with two-minute temporary radio leases. The RAK targets retained 2 dBm TX
power; the Tag used its saved 22 dBm. The excluded 910.525 MHz channel was
not used.

| Installed image | Exact-nonce round trips | Core errors before/after | Result |
| --- | ---: | --- | --- |
| RAK4631 Reduced Repeater | 3/3 | 0 / 0 | PASS |
| RAK4631 Full Repeater | 3/3 | 0 / 0 | PASS |
| RAK3401 Full Room Server | 3/3 | 0 / 0 | PASS |

After radio cleanup, the Room Server completed one 90.009-second nonhalting
SWD capture with power saving on: 6,374 sleeping observations among 8,035
samples, or **79.31% weighted sampled sleep**. There were no sampled resets,
halts, steps, interrupt masking or lockups; debug controls stayed unchanged.
Maximum read time was 3 ms and maximum sample gap 16 ms. Uptime advanced
continuously; the post-check had zero errors and an empty queue. This measures
sampled CPU states, not electrical current or exact sleep residency.

The first Room preparation stopped on an unsupported `ota bootloader status`
getter before any RF or CPU capture. Its failure and repeater restoration are
retained. The corrected room-only follow-up treats that optional status page
as unavailable while retaining mandatory bootloader-version and application
identity checks. It did not repeat the already-passing RAK4631 tests.

Final handback leaves both RAKs on patched Full Repeater images, saved 917 MHz
settings and power saving on. The RAK3401 gateway service is active again with
its original configuration and exact USB owner; final core errors were zero.

## Regression checks and CI

- 62 packet-manager cases, including four stale-wait reproductions that failed
  before their fixes; genuine timeout and live-owner backoff still pass.
- Three Meshtext and nine direct-OTA sanitizer cases; five receive-contract
  cases; startup-watchdog and radio-idle regressions.
- 55 RAM tests, 21 flood test methods and two OLED checks, including native
  sanitizers, ARM layout, all 63 rules, FPF6/7/8 compatibility, full-length
  names, room imports, fault recovery and malformed-file rejection.
- Actual CI now builds both RAK4631 Repeater profiles and both RAK3401 Room
  Server profiles, rather than relying on a Full Companion build alone.

The shared CAD fix initially exposed a 44-byte Mini Repeater flash overflow.
Mini-only CLI text was shortened without removing commands, values or checks.
Its exact release-wrapper build now passes at 245,696 of 245,760 application
bytes; RAM passes at 43,920 available against 32,288 required. Four replay
integration and eight Mini-profile tests passed. Other platforms select their
unchanged messages.

The updated [CI run](https://github.com/mikecarper/MeshCore/actions/runs/39909897061)
passed all 12 firmware and support jobs, including both new RAK build pairs.
The main test job exposed an outdated trace-timing extraction fixture: it
omitted the dispatcher's new queue helpers. The fixture now extracts those
production methods and supplies their state dependencies; all five test
methods and ten normal/mutation invocations pass with ASan/UBSan. This
fixture-only correction requires no repeated firmware or hardware checks.
These targeted checks do not claim a new all-board campaign, RS232 cable
traffic, physical OTA installation, maximum-load operation or a long RF soak.
