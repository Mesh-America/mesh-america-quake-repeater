<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/esp32_spi_clock_retune_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Heltec V3 and V4 SPI clock comparison, 23 October 2026

Status: **Completed. Raising SPI from 8 MHz to 8.888888 MHz saved less than
0.6% of average complete radio-profile switching time in these measurements.**
The production defaults remain 8 MHz on these two boards.

## Results

Each result combines both switch directions and two measured windows per
clock. Means are weighted by the actual number of complete switches.

| Board | Change between profiles | 8 MHz mean, us | 8.889 MHz mean, us | Saved, us | Saved, % | Samples, 8 / 8.889 MHz |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Heltec V3 | Frequency only | 774.608 | 774.146 | 0.462 | 0.060 | 3769 / 3743 |
| Heltec V3 | Frequency and modem | 909.121 | 904.614 | 4.507 | 0.496 | 3540 / 3801 |
| Heltec V4.3 OLED | Frequency only | 557.113 | 554.125 | 2.988 | 0.536 | 3700 / 3665 |
| Heltec V4.3 OLED | Frequency and modem | 685.295 | 682.891 | 2.404 | 0.351 | 3666 / 3667 |

The V3 frequency-only difference is smaller than its variation between
windows. All results are descriptive observations from two windows per clock,
not statistical confidence estimates. These are instrumented means, not
maximum switching times or production timing guarantees.

| Board / profile change | Range of window means at 8 MHz, us | Range at 8.889 MHz, us |
| --- | ---: | ---: |
| V3 / frequency only | 773.505-775.697 | 773.251-775.052 |
| V3 / frequency and modem | 907.838-910.219 | 903.381-905.868 |
| V4 / frequency only | 556.939-557.287 | 552.863-555.367 |
| V4 / frequency and modem | 685.169-685.419 | 682.745-683.038 |

The faster clock produced small improvements in individual bus-related
stages: the frequency stage improved by 0.54-1.18 us, and mixed-modem changes
improved modulation by 0.98-1.28 us and receive restart by 1.41-1.68 us.
Other stages varied in both directions. Stage getters have separate sample
boundaries, so their means must not be added to reconstruct the whole-switch
measurement or treated as proof of a single bottleneck.

## Physical setup and measurement

Both boards ran their Full observer MQTT Repeater targets from source
`601f3ee622621189b4acaa229639c4ef5be910f2`. Matching private test builds retained
the normal features and added these four flags:

```text
-DMC_SX1262_SPI_HZ=8888888
-DMESH_HIL_ESP_SPI_AB=1
-DMESH_HIL_PROFILE_TIMING=1
-DMESH_HIL_PROFILE_HISTOGRAM_COUNT=8
```

The same installed image was used for both clocks on each board. Explicit
`radio.fast.spi=8` selected 8 MHz; `radio.fast.spi=0` selected the test image's
8.888888 MHz default. All seven fast-switch feature settings, CPU selection,
power-saving policy, WiFi, Bluetooth and logging settings remained unchanged.
This comparison does not isolate differences between V3 and V4 hardware or
their target configurations.

Actual SPI divider readings, taken after a transaction began, confirmed both
clocks on both boards before and after every measurement window:

| Clock, Hz | Actual divider |
| ---: | --- |
| 8000000 | `0x00101001` |
| 8888888 | `0x00082001` |

The two receive-profile pairs were:

| Pair / profile | Frequency, MHz | BW, kHz | SF | CR | Preamble, symbols |
| --- | ---: | ---: | ---: | ---: | ---: |
| Both pairs / primary | 917 | 62.5 | 7 | 5 | 32 |
| Frequency only / secondary | 918 | 62.5 | 7 | 5 | 32 |
| Mixed modem / secondary | 918 | 500 | 5 | 5 | 200 |

For each pair, clocks alternated 8 / 8.889 / 8 / 8.889 MHz. Each window
contained 30 seconds without CLI getters, after effective profile application
and four successful self-test switches in each direction. The separate
120-second recommendation-display cooldown could remain pending; it does not
prevent the scanner from switching or the timing capture from recording.

Eleven instrumented stages covered the complete RX-to-RX path, including
admission, standby, frequency and modem configuration, and restarting receive.
The whole-switch mean was independently recomputed from atomic count and sum
deltas. Reads at window boundaries add a short, recorded span around the
central quiet period. No intentional RF test packets were transmitted;
ambient reception and ordinary firmware traffic were not controlled.

All 16 windows passed, totaling 29,551 complete-switch samples. There were no
new core error flags, switch errors or RXPS-watchdog recoveries. Both
boards already had core flag 8 and recovery history `soft=1,hard=0` before the
matrix, following their saved five-minute idle radio watchdog. Those baseline
values were retained and checked, rather than reset or counted as a new SPI
failure. Uptime advanced without a detected reboot during the measurements.

The compact histogram's final bucket is open-ended at 448 us. Its tail does
not establish exact percentiles. Cumulative minima and maxima also cannot be
reported as per-window extrema. In particular, these average results do not
establish a 500 us maximum or qualify packet delivery, CPU sleep or Bluetooth.

The first controller attempt stopped before collecting a window because it
checked asynchronously applied radio2 settings too early. A revised controller
waited for the effective profiles. A subsequent preflight detected the idle
watchdog baseline; it was diagnosed and explicitly recorded before the final
successful matrix. Neither incomplete attempt contributes timing samples.

## Firmware restoration and evidence

Temporary radio profiles and the original saved SPI selection were restored
after measurement. Both boards were then restored to normal, uninstrumented
Full observer MQTT Repeater images from source `601f3ee6`, using the original
8 MHz default. Application-only installation and complete application readback
passed; partition tables, OTA selection metadata and readable saved settings
were preserved. A final read-only inventory confirmed the same source and
identity, SPI selection 0 resolving to 8 MHz, all seven fast features on,
radio2 off, temporary profiles cleared, no test diagnostics and core flags 0.

| Normal firmware | Verified application body |
| --- | --- |
| Heltec V3 | `736232F76F3C8667` |
| Heltec V4.3 OLED | `CF58F8FF6B71A565` |

These restoration checks have separate receipts; they are not inferred from
the timing measurement's settings cleanup.

The [sanitized results](esp32_spi_clock_retune_2026-10-23.safe.json) retain
per-direction means, all eleven stages, counts, window-mean ranges, clock
proofs and restoration checks. Private hardware identities and raw CLI
responses are excluded.

Validation included five native diagnostic tests, four timing-capture tests,
two portable-HAL tests, 14 controller tests, 18 installer tests and nine
independent analysis tests. All four canonical Full images passed their
capacity checks without feature reductions. Hardware timing and restoration
receipts provide the physical evidence; the native tests validate capture,
control and analysis behavior.
