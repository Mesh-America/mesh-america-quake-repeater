# ESP32 Full idle power and compact AP validation — 2026-10-06

Tested firmware source: `219e936ef82d16539111f03bc7982dd5654412df`, after pulling
upstream through `5a7c07a6c`. Version:
`v1.17.1.9-halo-keymind-cascade-dev-powerap3-219e936e`.
PlatformIO commands ran one at a time in a native WSL checkout.
A later upstream test-only commit `f8e04f090` was merged without changing the
tested firmware sources; its 14 USB serial hygiene tests also passed.

## Corrections

Fresh expanded ESP32 Full profiles default USB packet logging off. Existing
saved logging and power-saving preferences remain authoritative. Repeater and
Room Server automatic setup with no saved SSID suspends unused network bridges
and their automatic retries. When the setup window ends, idle cleanup releases
the actual WiFi driver before sleep becomes eligible. Failed shutdown remains a
sleep blocker, and active/stopping WebConfig, MQTT, ESP-NOW, and OTA retain their
ownership. OTA resumes only bridges that were actually running beforehand.

Native USB Companion idle handling now checks the actual WiFi and Bluetooth
drivers, GPS UART, pending work, logging, host presence, and host-loss grace.
An enabled Bluetooth controller still blocks manual light sleep. This does not
change the deliberate raw-UART console or primary ESP-NOW sleep constraints.

Compact browser OTA and Companion setup use the shared scan-before-AP startup.
They require an AP-start event and correct live SDK configuration, protocol,
channel, and IP before reporting success. Scanner cancellation and stale Arduino
versus SDK state have explicit regressions. Browser OTA preserves inherited
LAN/ESP-NOW ownership, and repeated OTA start preserves joined clients on a
healthy AP. WebConfig setup disconnects STA to isolate its open setup API while
preserving an explicitly running ESP-NOW owner.

Physical testing caught an additional regression in the first candidate: manual
WiFi setup suspended explicitly enabled ESP-NOW. The final implementation limits
that suspension to automatic boot setup. Manual starts and master radio off/on
now preserve the requested WiFi/ESP-NOW subset. The regression test executes the
real infrastructure backend and wireless controller for both roles; reverting
the manual wrapper to automatic suspension makes it fail.

## Software checks

All 98 focused host tests in 20 suites passed. They include extracted production
startup, idle cleanup, sleep guards, USB host grace, saved preferences, OTA bridge
restoration, AP fault injection, and real wireless controller subset restoration.
The new suites are included in the unit-test workflow. A separate shared AP
fixture compiles Arduino 2/3 and open/password setup variants. Negative controls
demonstrate rejection of stale live SDK AP state and revived idle bridges.

All eight release builds passed linked capability, internal RAM, and app-slot
checks:

| Target/profile | MCU/core | App bytes | App slot bytes |
| --- | --- | ---: | ---: |
| Heltec V4 Repeater Full | ESP32-S3 / Arduino 2.0.17 | 2,100,584 | 6,553,600 |
| Heltec V4 compact LoRa OTA | ESP32-S3 / Arduino 2.0.17 | 1,283,304 | 1,310,720 portable ceiling |
| Heltec V4 Room Server Full | ESP32-S3 / Arduino 2.0.17 | 2,035,864 | 6,553,600 |
| Heltec V4.3 Companion Full FEM off | ESP32-S3 / Arduino 2.0.17 | 2,362,280 | 6,553,600 |
| Heltec V4 Sensor Full | ESP32-S3 / Arduino 2.0.17 | 1,493,976 | 6,553,600 |
| Heltec V2 Repeater Full | classic ESP32 / Arduino 2.0.17 | 1,675,432 | 3,342,336 |
| Xiao C3 Repeater Full | ESP32-C3 / Arduino 2.0.17 | 1,826,728 | 2,031,616 |
| Heltec RC32 without display Repeater Full | ESP32-S3 / Arduino 3.3.11 | 2,277,304 | 6,553,600 |

Full V4 SHA-256:
`ceb901afaba5f8012c49094122e30612dbf08518ebeffa51d8f92375cb52bc02`;
running body hash `8D26967FCC1A4984`; target ID `E792A051`.
Compact V4 SHA-256:
`7b00131b795b236ce42cf62a824fb5e30a3f934034a819bf5d7a5d71a55983c9`;
running body hash `EF44A3B4FE567589`; target ID `4D015420`.

## Physical checks

Mercerwood's Heltec V4.3 OLED was identified through its exact USB serial, board,
Repeater role, hardware family, running image hash/size, target ID, and expanded
two-slot partition layout. Only application slots were updated; partition
table, bootloader, identity, and ACL were preserved.

| Boundary | Result |
| --- | --- |
| Automatic boot with no SSID, temporarily saved WebUI/ESP-NOW enabled | PASS: fresh boot, working discovered/joined setup AP and cached scan results; unused ESP-NOW stayed suspended. Temporary saved flags were restored before manual cases. |
| Explicit ESP-NOW off/on, then manual WiFi on | PASS: ESP-NOW remained on through WiFi startup, AP connection, and portal stop. |
| Master 2.4 GHz off/on | PASS: individual on rejected while master off; both independently requested WiFi and ESP-NOW restored afterward. |
| Full AP after WiFi toggle, ESP-NOW toggle, master restore, and OTA stop | PASS: fresh beacon, association, HTTP 200, setup UI/API, cached scan results, and requested ESP-NOW ownership. |
| Full OTA AP after master off and repeated after stop | PASS: fresh beacon, association, HTTP 200, usable update page. |
| Compact explicit AP, restart after stop, and implicit `start ota` | PASS in all three cycles: fresh beacon, association, HTTP 200, lightweight raw uploader. |
| Full → compact → Full application uploads | PASS: each exact qualified image/target and application slot switch verified; final Full body `8D26967FCC1A4984`. |
| Restoration | PASS: original saved preferences, public identity, ACL, runtime radio flags, Pi WiFi, and wired route verified; temporary profiles removed, serial released, no cleanup errors. |

The compact direct-build alias displays `env:?` because the optional target-name
catalog has no entry for its ID. The harness stopped on that display after
upload, then resumed only after exact qualified body hash, size, version,
hardware, role, target ID, and slots were independently proven. Unknown bodies,
wrong IDs, and wrong named environments still reject. That guard stop is retained
in the sanitized evidence; it was not counted as a firmware pass.

The final node runs the new Full image with its original settings. It still has
saved power saving off and USB logging enabled. USB is attached and no current
meter is available, so actual sleep/current is unmeasured. The automatic setup
window expiration and sleep eligibility are covered by production-code host
tests; the physical check did not wait through the entire setup window.

Sanitized build, host-test, and physical evidence:
[`esp32_full_power_ap_2026-10-06.safe.json`](esp32_full_power_ap_2026-10-06.safe.json).
Actual ESP-NOW peer packet exchange, the reported iPhone client, saved-network
LAN recovery, and other boards' physical current/AP behavior were not qualified
by this transaction.

## Board scope and limits

The fixes use shared ESP32 code: Repeater/Room lifecycle, CommonCLI Full defaults,
ESP32Board browser OTA/sleep, and Companion setup. Other ESP32 boards inherit the
applicable fixes when rebuilt through their matching release profile. No normal
ESP32 board sleep override or alternate production AP path was found. Standalone
partition migration/legacy seed utilities retain separate AP code. nRF52,
RP2040, and STM32 do not use these ESP32 changes.

Build and host-test coverage does not establish each board's battery current.
Raw UART consoles, active BLE/controller, GPS UART, Ethernet/serial Companion
interfaces, native USB host grace, primary ESP-NOW, and intentionally enabled
logging can still inhibit manual sleep. Saved power-saving off also remains off
after updating. There is no claim of 11–14 mA consumption from this validation.

Future AP acceptance must verify fresh beacon discovery, association, working
pages/API, scan results, owner preservation, and cleanup on physical hardware.
CLI success and mocked SDK state alone are insufficient.
