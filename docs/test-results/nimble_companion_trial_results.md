# ESP32-S3 NimBLE trial results, 2026-09-08

These are local hardware trial results for USA Cascade Full Companions on a
Heltec V4.3 OLED and a Seeed XIAO ESP32-S3 with WIO SX1262. The V4.2 shares the
profile but was not physically tested. Build and command instructions are in
[the trial guide](nimble_companion_trial.md).

The final source revision is `9dbab431`, using NimBLE-Arduino 2.5.1 and the
existing Arduino-ESP32 2.0.17 toolchain. These optional profiles are outside the
ordinary release matrix. This trial does not change GitHub release assets or
the firmware picker.

## Capacity

| Measurement | Heltec V4 | XIAO S3 WIO |
| --- | ---: | ---: |
| Contacts / channels | 350 / 40 | 350 / 40 |
| PSRAM-backed offline queue | 512 | 256 |
| Application image, bytes | 1,774,600 | 1,510,536 |
| OTA application slot, bytes | 6,553,600 | 3,342,336 |
| Linked internal capacity before runtime allocation, bytes | 263,944 | 265,576 |
| Required runtime RAM budget, bytes | 173,056 | 148,480 |
| Headroom beyond that budget, bytes | 90,888 | 117,096 |
| Live free heap with Bluetooth and 350 test contacts, bytes | 142,644 | 147,444 |
| Minimum free heap during that contact test, bytes | 138,024 | 142,788 |

The live contact-test readings are from revision `7f1bd8b1`. Revision
`9dbab431` retains the same Bluetooth adapter, contact allocation and queue
sizes, and fixes the MQTT save stack use described below. Linked capacity is
not live free heap; the firmware memory reports label that distinction.

A matching V4 build using Bluedroid had 248,840 bytes of linked internal
capacity. NimBLE recovers 15,104 bytes at link time. The matching Bluedroid
application was 2,169,848 bytes. There was no matching physical Bluedroid heap
measurement, so these figures do not establish a live heap saving.

## Bluetooth hardware checks

Both boards passed the following cases with BlueZ on the Mercerwood Pi:

- PIN authentication, encryption, stored bonding, and bonded reconnection.
- MTU 179; accepted 176-byte writes and complete 148-byte contact notifications.
- Insert and synchronize all 350 synthetic contacts without missing or
  duplicate entries.
- Custom MAC address appears over the air in the entered byte order and
  persists across reboots.
- Saved random MAC persists; random-every-boot changes on each boot.
- Random-after-connect retains its address through an unauthenticated boot
  and rotates on the boot following an authenticated connection.
- Stealth first pairing, bonded-peer reconnection, and reconnection after
  reboot with a stable identity.
- Restore factory MAC and ordinary discovery.
- Three reconnect samples with no observed downward free-heap trend.

The complete MAC suite ran on `7f1bd8b1`. Final-image connection and update
checks also verify the unchanged adapter after the MQTT stack fix. Synthetic
contacts were removed after testing; factory MAC mode and stealth off were
restored.

## MQTT save stack overflow

The V4 test reproduced an actual reset while saving MQTT settings through
WebConfig. Serial output identified `Stack canary watchpoint triggered
(loopTask)`. `onConfigBatchEnd()` kept a second 2.8 KB preference copy while
the loader and NVS code also used stack space. Free heap was not the limiting
resource.

The loader already updates its destination only after validation, so the
callback now passes the live preference object directly. The actual Xtensa
callback frame shrank from 2,928 bytes to 32 bytes. The regression test
compiles the real callback with a 512-byte frame ceiling and demonstrates that
the previous nested-copy implementation fails the check.

On the corrected `9dbab431` image, the 11-setting WebConfig batch completed
with all entries accepted and no reboot. The V4 connected to a local
Mosquitto broker, published MQTT traffic, and kept its authenticated Bluetooth
session alive through a 30-second load interval with continuous uptime and
zero reported error flags. Free heap measured 120,684 then 122,140 bytes;
the minimum was 118,332 bytes and the largest free block was 110,580 bytes.
Disabling the test MQTT slot also completed successfully without reboot.

## WiFi updates and QR

Both boards completed real application-image uploads over WiFi with Bluetooth
connected, followed by reboot and reconnection using the saved bond. Repeated
HTTP page requests and Bluetooth status requests ran together before upload.
The image hash was checked before transmission, and the running firmware
version was checked after reboot.

The V4 WiFi setup page again contains a QR code. The default open setup SSID
fits a 44 x 44 pixel code: 2 x 2 pixel modules and an exact one-pixel white
border. The native test rendered the actual display/QRCode code and decoded
the result with ZXing. SSID, portal address and the hold-to-stop hint fit
beside it. Physical phone-camera scanning has not been verified.

## Observed limits

One XIAO warm reboot left its USB endpoint unresponsive while Bluetooth still
answered. The user's physical unplug/replug restored USB; the later full MAC
suite completed its commanded reboots successfully. The cause of that one
USB failure is unconfirmed.

The XIAO initially failed to associate with the saved WiFi network. Reapplying
the SSID scheduled a fresh connection, after which it joined at -53 dBm and
completed WiFi OTA. No antenna change was needed for that recovery.

This was functional hardware testing, not a long-duration soak. iOS/Android
app pairing, phone camera scanning, multiple TLS MQTT brokers, and an
end-to-end LoRa mOTA transfer were not qualified in this trial. The XIAO parent
profile does not include direct MQTT; the V4 does.

## Final application hashes

| Hardware | SHA-256 |
| --- | --- |
| V4 | `e6a1522ced4ed38ddd00e7cdf8393857224adbb622888a86370c0f7a3ee28d88` |
| XIAO S3 WIO | `ecf7afe6222e3897556a04e022515f9dcfcb825172dae9eaaa72eb92396dd004` |
