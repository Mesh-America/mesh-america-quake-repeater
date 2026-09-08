# Contact-cache and NimBLE RAM qualification

Test date: 2026-09-08. Firmware source: `b68aa1c6`.

All six constrained ESP32 Full Companion trials pass the linked RAM budget
at **350 contacts, 40 channels and 256 normal offline frames**. Their final
capability manifests confirm compiled Bluetooth/mOTA support and valid WiFi
OTA layouts.
These are the optional environments in the
[contact-cache guide](companion_contact_cache.md). Ordinary release recipes
retain their established contact limits pending qualification on those boards.

## Linked internal RAM

Every column below uses 350 contacts, 40 channels and 256 normal offline
frames. Values are bytes available for runtime allocations after linking.
The final margin subtracts the existing conservative runtime reservation;
it is not a measurement of live free heap.

| Hardware | Bluedroid | NimBLE | NimBLE + mOTA queue loan | Plus contact caches | Final margin |
| --- | ---: | ---: | ---: | ---: | ---: |
| Heltec V3 | 143,776 | 158,896 | 170,152 | 196,168 | 23,112 |
| Wireless Tracker | 148,432 | 163,536 | 174,792 | 200,824 | 30,838 |
| Tracker V2, FEM on | 133,064 | 148,168 | 159,416 | 185,456 | 15,470 |
| Heltec CT62 | 99,040 | 114,096 | 125,312 | 151,344 | 15,152 |
| XIAO ESP32-C3 | 98,816 | 113,888 | 125,120 | 151,152 | 14,960 |
| Generic ESP-NOW | 99,776 | 114,800 | 126,032 | 152,064 | 15,872 |

NimBLE recovers about 14.7 KiB. Contact caches add about 25.4 KiB on top of
NimBLE and the shared mOTA workspace. NimBLE alone fails the unchanged budget
at this capacity on all six; adding the queue loan passes only on the original
Wireless Tracker. Adding the contact caches passes all six, with 14.6-30.1 KiB
of margin. The same Bluetooth runtime allowance is used in every comparison.

The shared mOTA queue stays at 256 frames normally and retains 128 while
mOTA borrows its workspace, then returns to 256. A queue above 128 must be
synchronized before that workspace can be borrowed; unread frames are not
discarded to start mOTA. PSRAM-backed queues retain their existing policy.

The baseline builds use `b041fc7f`; the final builds use `b68aa1c6`, with the
same ESP32 Arduino 2.0.17 toolchain and NimBLE-Arduino 2.5.1 where applicable.

The CT62, XIAO C3 and Generic ESP-NOW applications fit two 1.5 MiB OTA slots
on 4 MiB flash. Their explicit trial layouts retain 896 KiB SPIFFS and the
existing SPIFFS/coredump addresses. Install the merged image over USB when
changing from the ordinary single-slot Full layout. The other three trials
also retain verified dual WiFi OTA slots. All six remain mOTA senders.

Additional builds check the platform and default-policy branches:

| Build | Available bytes | Reserved runtime bytes | Margin bytes | Policy |
| --- | ---: | ---: | ---: | --- |
| T096 Full, FEM on | 100,076 | 73,728 | 26,348 | nRF52 path/secret caches |
| RAK3401 Full | 99,900 | 50,976 | 48,924 | nRF52 path/secret caches |
| Wireless Paper Full | 187,360 | 152,576 | 34,784 | ESP32 caches, existing Bluedroid |
| V4 Full NimBLE | 263,944 | 173,056 | 90,888 | Complete contacts in PSRAM |
| XIAO nRF52 legacy BLE Companion | 84,368 | 38,688 | 45,680 | Existing inline contact storage |

The V4 test-only forced-cache build also passes its RAM budget. The V4 normally
keeps complete contacts in PSRAM; forcing caches adds internal RAM overhead.
The six-board savings above apply to boards without PSRAM.

## Physical checks

The VM V4 used the test-only cache override. USB tests verified all 350
contacts and all 64 saved path bytes per contact, cold individual lookups,
replacement of the complete path set, and persistence after reboot. A secret
workload contacted 21 distinct synthetic peers, then the first peer twice:
22 calculations, one RAM hit, and no secret-file access under the ESP32 policy.

A sustained send test exposed a false receive watchdog recovery. RX could
occur inside the main loop between two successful transmissions, while the
watchdog observed TX at both loop boundaries. It counted from the start of
the whole burst and could reset a working radio during a later CAD pause.
`468cc3cf` restarts the receive recovery allowance after each successful TX.
The native regression fails before that change and passes afterward; it also
checks that a stuck receiver still gets recovered.

The corrected V4 passed the same 23-datagram workload with zero radio error
flags. It also passed a complete 350-path replacement, another send workload
and a post-reboot path check with zero radio error flags. The replacement
took about 127 seconds: dirty-cache eviction still performs synchronous
SPIFFS contact-file saves, so bulk path updates remain a latency workload
to qualify on the other ESP32 boards. After that run it reported 133,828 bytes free internal heap, a minimum
of 130,976 bytes, and a largest free block of 122,868 bytes. These readings
belong to the forced-cache V4 workload, not the six other boards.

After qualification, the VM V4 was erased to remove synthetic contacts and
installed with the normal PSRAM-backed V4 NimBLE trial from `b68aa1c6`. It is
named `NimBLE-V4-VM`, uses the PIN shown on its display, and has powersaving
off for USB use. That clean setup reported 143,612 bytes of free internal heap
and passed 201 local USB requests with zero radio error flags. The Mercer V4 and
XIAO S3 were left on their previously qualified NimBLE builds.

The Mercer RAK3401 Full Companion verified 350 paths, eviction and persistence.
Its first secret workload produced 21 calculations, one flash hit and one RAM
hit with no skipped saves. After reboot, the same workload produced 22 flash
hits, one RAM hit and **zero calculations**. Both completed with zero radio
error flags. The final `b68aa1c6` RAK image repeated the 350-path and saved-secret
checks with zero radio errors and zero calculations. The RAK was returned to
the published `26303793` repeater
application with its original repeater name and USA Cascade settings; the
Pi's MQTT logger was restarted after the exclusive USB tests.

## Shared-secret timing

| Hardware/filesystem | Successful saved-secret lookup | Key exchange | Selected miss policy |
| --- | ---: | ---: | --- |
| V4 / SPIFFS | 132,427 us | 21,932 us | Recalculate |
| RAK3401 / LittleFS | 7,812-8,789 us | 31,250 us | Read saved entry, calculate on miss |

The SPIFFS timing comes from the earlier forced flash-cache experiment. The
final ESP32 policy does no secret-file I/O. Both platforms reuse the 16 most
recent secrets from RAM. These are elapsed-time measurements, not energy
measurements; timing on other ESP32/nRF52 boards remains to be measured.

## Regression checks and evidence

The contact-cache suite exercises the production cache and persistence code
under address/undefined-behavior sanitizers, with the real Ed25519 key-exchange
implementation. Its cases include 350 paths, identity changes, snapshots,
legacy migration, storage faults, handle exhaustion and packet release when
a cold path cannot be read. The related contract suites passed 62 checks.
The native queue/store suites passed 27 cases, the radio-liveness suite passed
eight, and the partition-selection suite passed 11.

Hardware reproduction commands are in the
[contact-cache guide](companion_contact_cache.md#regression-checks). The tracked
harness is `tools/hil/contact_cache_serial_stress.py`. It requires exclusive
access to the specified Companion data port.

Local evidence in the qualification workspace:

- `.releases/nimble-six-capacity/control/results.json`: 18 baseline builds.
- `.releases/contact-cache/qualified/control/results.json`: final build results.
- `.releases/contact-cache/qualified/built/`: firmware, ELFs, maps, RAM reports,
  partition tables and capability manifests.
- `.releases/contact-cache/qualified/control/`: final V4 USB and flash checks.
- `.releases/contact-cache/control/`: earlier experiments, RAK results and
  regression logs, including the watchdog's failing/passing test runs.

Each final RAM report is checked against its ELF hash. All 12 final builds pass
their RAM and OTA capability checks. Physical testing here covers the V4 and
RAK3401; the six constrained ESP32 boards still need pairing, WiFi/BLE/LoRa
coexistence and sustained-load testing on their own hardware. No GitHub release
assets or firmware-picker entries were replaced by these experimental builds.
