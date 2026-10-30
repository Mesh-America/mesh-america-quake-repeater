<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/rak3401_radio2_recommended_preamble_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# RAK3401 recommended-preamble repeat, 23 October 2026

Status: **RF measurement complete, delivery FAIL. Debugger capture integrity
also FAILS its original sampling-gap limit.** The firmware's settled
recommendation of **radio1 preamble32 / radio2 preamble200** did not eliminate
the scanner's loss. Both fixed witnesses received all applicable packets.
The [sanitized receipt](rak3401_radio2_recommended_preamble_2026-10-23.safe.json)
records the RF evidence and retains the debugger limitation.

## Comparison with preamble384

| Radio2 preamble | RAK primary / 100 | RAK secondary / 100 | Fixed primary / 100 | Fixed secondary / 100 |
| --- | ---: | ---: | ---: | ---: |
| [384, previous completed run](rak3401_radio2_sf5_bw500_p384_2026-10-23.md) | 97 | 100 | 100 | 100 |
| 200, settled recommendation | 96 | 98 | 100 | 100 |

Primary remained **917.000 MHz, SF7, BW62.5 kHz, CR5, preamble32**; secondary
remained **918.000 MHz, SF5, BW500 kHz, CR5, RX mode**. Only the explicit
secondary preamble changed, including the matching sender and secondary
witness settings. RAK3401 still ran Full unified Repeater source `adb11e7b`;
Tag sender and T1000-E primary witness ran Companion `08650f64`, and the T096
secondary witness ran Companion `4773ac42`. No firmware was built or flashed.

Before any measured transmission, the controller waited for the two-minute
recommendation observation and checked the live response:

```text
chirps=4.60,328.05; need=32,200; switch=1176us; loop=0us; test=4/4,4/4 ready
```

Live effective preambles were `32,200`, with visits `9421,20995` us. The
guarded switch allowance and visits matched the previous completed run.
The controller would abort without transmitting if the settled recommendation
differed from the selected values.

The Tag sent 200 fresh, unique, 92-byte RAW_CUSTOM payloads in the same seeded
twenty-batch plan: 100 per profile, at 2 dBm. Physical packets were 94 bytes.
The nominal post-TX_DONE gaps remained 0.5-0.9 seconds, extended as needed for
confirmed sender retuning. The RF window lasted **203.294 seconds**. There
were exactly 200 physical direct transmissions, zero floods and no retries
or replacement packets. This was successive traffic from one sender, not
simultaneous transmissions on both profiles.

## Packet and health evidence

RAK missed primary **P032, P078, P079 and P087** (global zero-based ordinals
61, 147, 148 and 176), and secondary **S014 and S029** (ordinals 33 and 48).
Every missing packet reached its fixed witness. Both witnesses independently
matched all 100 custom-payload pushes and all 100 corresponding raw-frame
pushes. Each pair of observations counted as one delivery.

The RAK's physical receive counter advanced by 194, agreeing with its exact raw
packet ledger. There were no log drops, collector errors, framing losses,
duplicates or opposite-profile witness deliveries. All three receivers
transmitted zero packets during the RF window, and all four radios added
zero receive/CRC errors. Historical core masks remained 8/8/0/8 for RAK,
Tag, T1000-E and T096 respectively. RAK soft/hard watchdog counters stayed
0/0; queues were empty and uptimes remained continuous.

These finite counts show that preamble200 was not an improvement in this
run. One batch per preamble, collected at different times with uncontrolled
ambient RF, does not establish a universal performance ranking or identify
the cause of the six misses.

## Debugger limitation and restoration

The same nonhalting read-only SWD plan completed **300.004 seconds and 27,086
samples**, with exact before/after hardware identity matching. Samples showed
no debug enable, halt, stepping, interrupt masking, reset or lockup. OpenOCD
returned normally. However, one **27.5 ms** midpoint gap between samples 11103
and 11104 exceeded the frozen **25 ms** acceptance limit. Timestamps remained
monotonic and all sample reads took at most 3 ms. **The integrity failure is
retained, not waived.** The controller therefore did not award an overall pass.

The sampling gap occurred around 121.7 seconds into RF collection; the six
misses occurred around 35.33, 46.84, 61.38, 150.90, 151.96 and 179.22 seconds. It did
not overlap a missed packet. RF receipt validity comes from independent USB
collectors, witness raw frames and exact physical counters; it does not rely
on uninterrupted debugger sampling. This capture does not qualify CPU sleep:
the active USB data/logging session keeps the repeater awake.

All four nodes passed settings preservation. Temporary leases were removed,
RAK live radio2 returned to off, original power/logging settings were retained,
and the unchanged gateway service reacquired its radio. Independent offline
analysis confirmed the packet losses and the separate debugger failure.
