# Heltec V4 preview4 Bluetooth/OLED regression validation

Date: 2026-10-02. These are observations on one physical Heltec V4.3 OLED,
not qualification of every board or phone. The preview4 images are local,
unreleased builds with uncommitted changes on `keymindCascade` at
`7324bf06efef236009dac2d507775fa4e19bc856`.

## Target and method

- Host: MercerWoodMesh Raspberry Pi, built-in BlueZ Bluetooth controller.
- Target: Heltec V4.3 OLED, ESP32-S3 revision 0.2, 16 MB flash, 2 MB PSRAM;
  exact USB serial `44:1B:F6:69:CF:98`.
- Version under test: `v1.17.1.8-preview4`, build 02-Oct-2026, USA Cascade
  Full Companion, OLED, no expansion, NimBLE-Arduino 2.5.1.
- Diagnostic environment: `heltec_v4_companion_pairing_ui_hil_preview4` in
  `platformio.heltec-v4-preview4.ini`.
- Diagnostic application SHA-256:
  `df0c109e7c3e99e43ec388a4017da8971f41572f51afeac779cddc4a56e69d14`.
- Helper: `tools/hil/v4_pairing_stealth.py`; Linux `bleak`, `dbus-fast`,
  `pyserial`, target-restricted passkey agent. Test PIN **246810**, deliberately
  different from NimBLE's 123456 callback sentinel.

A complete, hash-checked 16 MB original flash backup was taken first. Only
`otadata` and the application were written for the temporary diagnostic image;
the bootloader, partition table, NVS and SPIFFS were retained. No other Pi radio
was flashed. The helper did not request LoRa transmissions; ordinary background
radio activity was not disabled.

`COMPANION_PAIRING_UI_HIL` is an opt-in diagnostic macro, absent from production
builds. It records actual startup phases, display power/pairing/USB state, public
identity, and the real 1024-byte SSD1306 framebuffer. It does not access the
private key. Frame capture occurred during an actual outstanding passkey
request, not a manually invoked firmware callback.

## Observed hardware results

| Check | Result |
| --- | --- |
| Fresh pairing with a non-default PIN | Passed twice: exactly one actual passkey request per fresh pairing; BlueZ reported Paired and Bonded. |
| PIN display while USB remains connected | Passed twice: display on, pairing active, USB present, and captured frame containing `PAIR PIN 246810`. This verifies the display driver's real framebuffer and wake state, not an optical photograph. |
| Protected BLE transport | Passed: MTU 179, 82-byte device-info response and 176-byte ATT command payload, live CLI/status responses, zero core error flags. |
| Custom MAC with stealth | Passed: fresh discovery/pairing, live `bonded-peer-only advertising` status, bonded reconnect with no new PIN, then USB-commanded reboot and another bonded reconnect with no new PIN. |
| Saved random MAC | Passed: USB-commanded reboot retained its address with stealth enabled. |
| `random-after-connect`, unused boot | Passed: reboot over USB, without BLE authentication, retained the address. |
| `random-after-connect`, authenticated boot | Passed: actual authenticated BLE connection armed the next boot; address stayed unchanged during that session and changed on the following USB reboot. The new address was discoverable with stealth retained. |
| `random-every-boot` | Passed: two successive USB-commanded boots used different addresses, with stealth enabled. |
| Saved identity startup | Passed: Starting/Loading phases only, no Generating/Saving phase. The same public identity was retained throughout the run. |

The suite finished with `suite_passed`, six observed application addresses,
two captured OLED frames, and `identity_preserved: true`. An earlier harness
attempt stopped because it did not recognize a terminal prompt immediately
followed by a diagnostic line; the parser was corrected and the complete suite
rerun. This was not a BLE pairing failure.

Stealth on ESP32 uses minimal, unnamed, allowlisted advertising after pairing;
it is not radio invisibility. Bonded reconnection and policy/rotation behavior
were tested here. Actual advertising-payload capture and rejection of an
unbonded second central were not part of this run.

## Original target restored

After the suite, the complete original 16 MB image was written back. Esptool
verified the flash data hash. Live serial readback then confirmed:

- Original version:
  `v1.18.0.1-halo-keymind-cascade-dev-app-wifi-test-6f6d1a2a`,
  protocol 14, build 01-Oct-2026.
- Original board and public identity unchanged.
- Bluetooth on, factory/default MAC, stealth off.
- Original default Bluetooth name, USB display mode `button-pairing`, and
  USB logging off.

The full backup remains private on the Pi. Raw diagnostic logs and captured
OLED pixels remain in the ignored local preview4 output folder; neither the
backup nor unreviewed radio logs are published. Only test-created BlueZ device
records were removed by the helper.

## Automated regression coverage and builds

- 117 targeted native cases passed across identity generation, display layout,
  serial routing, and Companion preferences. This was not the entire native
  suite.
- 39 Python cases passed across the real NimBLE adapter, pairing UI, saved/new
  identity startup, startup display, display power, MAC/stealth contracts,
  settings persistence, inbox rendering, preference transaction, and Bluetooth
  control suites. Executable C++ fixtures use the production implementation;
  sanitizer-enabled fixtures also passed.
- The unit-test workflow now includes the real NimBLE callback dispatch,
  USB-connected pairing display, identity-startup, and startup-screen suites.
  No GitHub run was triggered for these uncommitted changes.
- Production V3 and V4 Full Companion preview4 builds passed linked-memory
  qualification. Available/required internal heap: V3 200,144/182,016 bytes;
  V4 252,152/177,920 bytes. Diagnostic V4: 252,136/177,920 bytes.

The NimBLE regression fixture reproduces the pinned library's dispatch rule:
a non-default static passkey bypasses `onPassKeyDisplay()`. Firmware now leaves
NimBLE's sentinel at 123456 and returns the actual configured PIN through that
callback, preserving authentication while notifying the UI. Tests cover random
and saved PINs, USB coexistence, button wake/navigation, disabled display/BLE,
saved identity, generation, persistence failures, and removal of the generation
label once generation finishes.

## Remaining hardware gates

- Physical Heltec V3, including its user button; the Pi board here was V4.
- Optical OLED inspection and physical button gestures (covered in executable
  host fixtures, not remotely actuated on this board).
- Android/iOS MeshCore apps, privacy-address reconnection, and an unbonded
  second physical central.
- Actual post-pairing advertising payload capture.
- All-power-removed cold boot; this run used commanded reboots only.
- Destructive missing/corrupt identity and bond/write-failure injection on
  hardware; these branches were exercised by host fixtures without erasing
  the real node's identity.
