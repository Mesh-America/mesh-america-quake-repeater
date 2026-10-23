<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/rak3401_radio2_fast_switch_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# RAK3401 radio2 fast switching, 23 October 2026

Status: **PARTIAL. Switching improved; the 500 us maximum goal is not met.**
The production candidate retains buffered 8 MHz SPI on SPI1/SPIM2. Private
16 MHz experiments failed radio initialization or returned incorrect radio
readback. They are not production defaults. **Fresh witnessed RF delivery
qualification failed: the scanner received 195 of 200 test packets.**

## Timing checkpoints

These are hardware measurements of the RX-to-RX profile-switch path, including
admission, standby, changed radio parameters and restarting receive. They are
not bare PLL-lock times. The production budget uses the sampled maximum plus
a rounded-up 10% margin; it is not a guarantee against a larger future sample.

| Source | Change | Sampled maximum, us | Guarded budget, us |
| --- | --- | ---: | ---: |
| `adb11e7b` | Original 2 MHz, byte-at-a-time SPI | 1069 | 1176 |
| `99979655` | Buffered 2 MHz SPI | 855 | 941 |
| `258b37df` | Buffered 2 MHz plus modem/IQ caches | 702 | 773 |
| `b8b7880a` | Buffered 8 MHz plus caches | 550 | 605 |
| `1b97c089a` | Normal 8 MHz production image, longer RF campaign | 611 | 673 |

The ordinary nRF52 switch budget uses the 32,768 Hz RTC2 clock, approximately
30.52 us per tick. A separate 64 MHz DWT instrumentation build from
`2629c158` captured 586 successful switches in each direction:

| Direction | Minimum, us | Mean, us | Maximum, us |
| --- | ---: | ---: | ---: |
| Primary to secondary | 410 | 415.643 | 555 |
| Secondary to primary | 409 | 414.614 | 550 |

Both directions recorded zero busy admissions and zero failed switches in
that capture. DWT stage counters, later interrupt observers and experimental
guards add work. Times from differently instrumented builds are not directly
comparable with each other or with production timing. A mean below 500 us
does not satisfy the requested maximum.

## Why 16 MHz is not enabled

The pure Repeater failed startup at 16 MHz on SPIM3 with RXDELAY settings
0, 1 and 2. Read-only SWD captures showed completed SPI frames, SoftDevice
disabled, and no observed fault-register evidence in those snapshots. This
does not support blaming those particular failures on Bluetooth or USB
enumeration. It also does not establish a hard clock limit for the pins.

A narrower diagnostic initialized the radio successfully at 8 MHz, then
issued 16 read-only GetPacketType commands at each of 8, 16 and 8 MHz. No
radio writes or resets occurred between phases. The controller, pins and
explicit anomaly-198 workaround remained the same; the per-frame SoftDevice
safety check remained active.

| RXDELAY | Initial 8 MHz correct / 16 | 16 MHz correct / 16 | Restored 8 MHz correct / 16 |
| ---: | ---: | ---: | ---: |
| 2 | 16 | 4 | 16 |
| 1 | 16 | 3 | 16 |
| 0 | 16 | 2 | 16 |

The first two raw response bytes, `A2,A2`, are normal for these reads. The
failure is the final packet-type byte differing from the expected LoRa value
`01`. Restoring 8 MHz restored all 16 correct reads in every trial. This
isolates a reproducible fast-read problem after successful initialization;
it does not identify whether its cause is signal timing, the controller or
another part of the SPI path. No 16 MHz shipping claim is made.

## Experimental scheduling and interrupt controls

Task-priority elevation, bounded USB interrupt deferral and their explicitly
enabled combination were slower in the measured builds. All remain private,
default-off HIL options. The combined experiment did not achieve the 500 us
maximum goal.

One combined worst-hop capture reported zero activity for all seven observed
interrupt/scheduler sources. Shared TWI0/SPIM0 coverage was then added in
`aa480ae79`; the exact linked vectors and scheduler call were verified before
the physical test. Both directions completed 591 successful switches with no
failed switches; the reverse direction also recorded 12 busy admissions.
The slowest forward switch took 659.109 us and
again recorded zero activity, now across all eight observed sources. The
reverse maximum was 575.234 us. SysTick ENABLE and TICKINT were both off when
read after stopping the test. These observations rule out attribution to
the recorded sources for that forward hop, without proving a particular
memory, peripheral or CPU-stall cause. Observer overhead and inclusive handler
timing also prevent treating these counters as a complete or additive
explanation of elapsed time.
The observer excludes architectural exception paths and the experiment's
RTC2 deadline handler; the USB guard recorded no deadline expiry. The retained
worst sample is selected by integer microseconds, so equal-microsecond ties
can differ in raw cycles.

## Production scope and validation

The RAK3401 production path uses buffered SPI1/SPIM2 at 8 MHz. It does not
enable the global nrfx SPIM3 anomaly-198 workaround, which is unsafe with an
enabled SoftDevice. The newly buffered, unqualified nRF default-SPI/SPIM3
constructor rollout was restored to its prior defaults in `4e513b19d`.
Previously buffered LR1110 targets retain their prior constructors. Shared
cache improvements and the ESP32/RP2040 improvements remain. SenseCAP
Indicator is excluded, and MeshPocket has not been physically tested in this
campaign.

Focused native checks passed for buffered transfers and constructor/bus
selection, cache invalidation, CPU-clock policy transitions, timing captures,
SoftDevice refusal, read-probe timeout/restoration/recovery decisions, and
default-off experiment gates. Relevant native fixtures execute the actual
helpers; sanitizer checks cover the diagnostic paths. These checks do not
replace hardware qualification.

Cross-architecture build receipts include RAK3401, RAK4631, ThinkNode M4,
Heltec V2/V3, ESP32-C6 and Pico W targets. They cover campaign checkpoints,
not every board, firmware role or final-source image. The raw
`Station_G2_repeater` PlatformIO target exceeded its default 1,310,720-byte
application limit both at the baseline and after the changes; that
pre-existing overflow remains a separate build limitation. No all-builds or
all-boards release qualification is claimed here.

## Fresh witnessed RF test

The normal production image from `1b97c089a` was installed and its running
body hash matched the retained Full ELF/package. Two fixed receivers witnessed
the same 200 fresh, one-shot test packets, with no test-packet retransmission.
The settled recommendation was 32/192 symbols; the test selected 32/200.

| Receiver | Primary received / sent | Secondary received / sent |
| --- | ---: | ---: |
| RAK3401 scanning both profiles | 96 / 100 | 99 / 100 |
| Fixed primary witness | 100 / 100 | - |
| Fixed secondary witness | - | 100 / 100 |

There were no duplicate test packets, wrong-profile receipts, collector drops,
new core error flags, watchdog recoveries or switch-command errors. The RAK
recorded one additional receive error. The five-minute nonhalting CPU-status
capture passed its integrity gates: 27,134 samples, maximum gap 17 ms, no CPU
halt/debug enable, reset or lockup in the observation window. USB was active,
so this does not qualify CPU sleep or electrical power consumption.

The gateway and RAK settings were restored. The sender's original transmit
power restoration initially returned a radio-busy error; a separate settings-
only cleanup continuation was required. The original failed receipt was
preserved. Packet delivery qualification and the 500 us goal both remain
failed; an offline audit independently reproduced the same five missing
packets.

## Remaining work

The [earlier witnessed RF run](rak3401_radio2_sf5_bw500_p384_2026-10-23.md)
lost three primary packets while its fixed witness received all 100. A
[recommended-preamble run](rak3401_radio2_recommended_preamble_2026-10-23.md)
also had scanner losses. The new test confirms that scanner packet loss
remains after these speed improvements. Faster switching alone has not fixed
delivery.

The additional interrupt observer has completed its physical test. The normal
production image was built separately from `1b97c089a`, with all HIL helpers
absent and SPI1/SPIM2 selected; the later observer change affects HIL only.
Fresh witnessed RF testing of that production image is complete and failed.
The remaining work is to fix packet loss, explain and reduce the remaining
long switching intervals, and requalify the changed implementation. The
500 us maximum remains unmet.

Machine-readable [sanitized results](rak3401_radio2_fast_switch_2026-10-23.safe.json)
record the same scope and failures.
