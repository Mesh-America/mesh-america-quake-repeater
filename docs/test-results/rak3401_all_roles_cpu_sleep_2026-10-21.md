<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/rak3401_all_roles_cpu_sleep_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# RAK3401 all firmware CPU sleep checks, 21 October 2026

All 15 applicable images were installed and measured sequentially on the same
RAK3401. **All 13 profiles that support power saving passed the CPU sleep
capture with PS on.** Twelve also passed every runtime check. Full Room Server
slept correctly but raised a channel-busy timeout flag, so its overall result
remains failed. Terminal Chat and KISS expose no PS setting and showed no sleep.
The campaign therefore is not an all-modes qualification pass.

The board is left running **Full unified Repeater at `efad0076`, PS on**.
Its final core snapshot had zero error flags and an empty queue. The original
`mctomqtt.service` and exact USB ownership were restored without changing its
configuration. Updates used application-only packages; the reported bootloader
version is unchanged.

## Results

Each row has a complete 90-second CPU capture and an independently matched
whole-application readback. Percentages are weighted estimates from sampled
processor states, not exact sleep residency or current measurements.

| Firmware/profile | Source | PS | Sleeping/total samples | Sleep estimate | Result |
| --- | --- | --- | --- | --- | --- |
| Full Companion | `e16db810` | on | 5,510/8,000 | 68.78% | Pass |
| USB Companion | `e16db810` | on | 6,115/7,999 | 76.41% | Pass |
| BLE Companion | `e16db810` | on | 5,931/8,014 | 74.03% | Pass |
| Full Room Server | `e16db810` | on | 5,929/8,009 | 74.01% | CPU pass; health flag |
| Reduced Room Server | `e16db810` | on | 5,487/7,980 | 68.67% | Pass |
| Full Sensor | `e16db810` | on | 5,890/7,992 | 73.82% | Pass |
| Reduced Sensor | `e16db810` | on | 6,099/8,028 | 76.00% | Pass |
| Terminal Chat | `e16db810` | unsupported | 0/8,012 | 0.00% | PS unsupported; no sleep |
| KISS modem | `e16db810` | unsupported | 0/8,054 | 0.00% | PS unsupported; no sleep |
| Full Serial1 RS232 repeater | `efad0076` | on | 6,257/8,134 | 76.94% | Pass |
| Reduced Serial1 RS232 repeater | `efad0076` | on | 6,428/8,094 | 79.53% | Pass |
| Full internal-flash OTA repeater | `efad0076` | on | 6,275/8,106 | 77.38% | Pass |
| Reduced internal-flash OTA repeater | `efad0076` | on | 6,138/8,073 | 75.94% | Pass |
| Reduced unified OTA repeater | `efad0076` | on | 6,393/8,019 | 79.69% | Pass |
| Full unified OTA repeater | `efad0076` | on | 5,875/8,013 | 73.19% | Pass |

The [safe receipt](rak3401_all_roles_cpu_sleep_2026-10-21.safe.json) records
application/package hashes, source commits, capability and memory checks,
capture flags, timings and final handback health. All 15 capture-integrity
checks passed; no halt, step, interrupt masking, lockup or reset was sampled
inside any capture window. Debug-control state remained unchanged.

Full Room Server's `core.errors` changed from 0 to 2 at uptimes 51 and 148
seconds. The value is a bitmask: `0x02` is the latched CAD/channel-busy timeout
flag. The dispatcher bounds its channel-busy wait, records this flag, then
permits a transmit attempt. The observation does not establish the cause of
that busy condition or prove subsequent RF delivery. The CPU capture passed
at 74.01%, but the strict zero-error post-check failed and remains visible.
The failed result was retained, and this unchanged capture was not repeated.

Terminal Chat and KISS have no power-saving command or application idle-sleep
integration. Both completed valid captures with zero sleeping observations;
they are unsupported PS coverage, not PS-on passes.

## Hardware and procedure

The tested assembly is one RAK3401 core with an external RAK13302 radio and no
external NOR flash. Coverage includes Full/USB/BLE Companion; Full/Reduced
Room Server and Sensor; Terminal Chat and KISS; and Full/Reduced Serial1 RS232,
internal-flash LoRa OTA and unified OTA repeaters. The dedicated RAK13302 plus
W25Q16 image is excluded because its required external flash is absent. The
unified image exercised its no-NOR/internal-storage path.

The nine non-repeater images are bound to `e16db810`; the six repeaters are
bound to `efad0076`, after the build corrections below. No claim is made that
all images came from one revision. One application was active at a time, with
an exact application readback before each measurement. No bootloader or
SoftDevice package was installed.

Supported roles acknowledged `set powersaving on`, confirmed the saved value,
and provided a fresh RAM-only diagnostic window. USB command ports were closed
for capture. Companion intentionally prevents idle sleep with a configured USB
host, so only this target's USB data authorization was temporarily disabled
while retaining power, then restored. BLE sessions were disconnected for idle
capture and authenticated again afterward.

The nonhalting SWD sampler used MEM-AP reads of DHCSR at jittered 7–13 ms
intervals for 90 seconds. Sleep acceptance requires at least 5,000 samples,
100 sleeping observations, complete timing and chip-identity checks, unchanged
debug controls, and no sampled reset/halt/step/masking/lockup. Read timing must
remain within the 10 ms read and 25 ms gap limits. This measures observed CPU
sleep states, not just a firmware eligibility counter.

Five early preparations stopped before PS setting or CPU sampling: Full/USB
Companion on an arrow-prefixed reply, Full/Reduced Room Server on the first
version reply, and Terminal on LF/CRLF handling. The private reader was
corrected; a bounded retry of only the read-only version getter retained the
first unsupported reply. Their first actual CPU captures appear above, with
the earlier failed preparations retained in the JSON. Completed captures were
not repeated. An interrupted read-only Sensor application readback was also
preserved separately; it did not alter the installed image or repeat a CPU
capture.

## Build corrections

Commit [`efad0076`](https://github.com/mikecarper/MeshCore/commit/efad0076816f7ba2293c68f56f8db18ac17344b9)
fixes two defects exposed while preparing the matrix. All 15 selected packages
then passed their build, capability and memory gates.

The Full internal-flash and unified repeaters originally missed the required
runtime heap reserve by 412 and 564 bytes. Qualified nRF52 repeaters now use
the existing grouped Merkle-proof workspace instead of retaining every source
leaf: a 1,536-byte allowance replaces 4,096 bytes, saving 2,560 bytes of
worst-case active heap. The 1,024-block source capacity, wire proofs, sensors,
tables, stack and remaining reserves are retained. No admission gate was lowered.

The Serial1 RS232 recipe already disables GPS because the bridge owns that
UART, but its release capability contract incorrectly required GPS. Both
RAK3401 bridge profiles now follow the existing UART ownership contract while
retaining the INA monitor drivers. Compatible recipes retain their GPS checks.
Validation passed 49 RAM tests, four source-proof suites and two GPS-contract
tests. The proof suites include sanitized nRF52 Full/Reduced runs through the
unchanged 1,024-block maximum, byte-identical proofs, allocation ownership,
backpressure and simultaneous fetching/serving.

This finite sleep campaign does not qualify RF delivery, LoRa OTA installation,
UART peer traffic, external storage, regulator savings or battery life.
Application readback covers the package bytes, not protected storage or user
data; an unchanged runtime bootloader version is separate from a full
bootloader-byte preservation check.
