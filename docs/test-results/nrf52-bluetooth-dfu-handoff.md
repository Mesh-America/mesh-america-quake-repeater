# nRF52 Bluetooth DFU handoff

## Confirmed application defect

The released RAK4631 application
`RAK_4631_repeater-v1.17.1.7-halo-keymind-cascade-dev-2d03e098`
contains an unsafe transition from the running application into the Bluetooth
DFU bootloader. This transition belongs to the application's Bluefruit
`BLEDfu` service. Replacing the bootloader does not replace that application
code.

The original callback changes `CONTROL` to select the main stack pointer
(MSP) while its compiler-generated C frame still belongs to the FreeRTOS
process stack pointer (PSP). The compiled callback then restores its C frame
using MSP. With the observed stack state, that restore reads outside nRF52840
SRAM before reaching the bootloader entry point. A compiler/emulator
regression reproduces the fault.

This defect explains why a Bluetooth flasher can reach "enabling bootloader"
and then lose the device before the application transfer starts. It is
consistent with the reported solid blue LED and later application restart.
The exact reset cause and timing in the user's report remain unrecorded.
The standard application enables a 60-second watchdog; Android can also
report a separate 30-second GATT connection timeout. See the physical
comparison below rather than attributing every timeout to the watchdog.

## Application fix

`scripts/nrf52_ble_dfu_fix.py` patches a private build copy of the pinned
framework's `BLEDfu.cpp`. It preserves the legacy `B1` DFU entry marker,
retained peer/bond record, and SoftDevice vector-table handoff. It leaves
PlatformIO's shared framework cache unchanged.

The callback now enters the naked, nonreturning assembly helper
`mesh_nrf52_dfu_jump`. The helper loads the bootloader vectors, sets its MSP,
selects MSP, clears inherited interrupt masks, and branches directly to the
bootloader. No compiler-generated C stack access follows the stack switch.
The supported handler-mode path constructs an explicit exception-return
frame. The callback also clears SysTick, pending FreeRTOS system exceptions,
and both external interrupt banks before the handoff.

Every environment inheriting `nrf52_base` uses the private patch and the
compiled-image check in `scripts/check_nrf52_ble_dfu_handoff.py`. The check
requires the qualified helper instructions, rejects a `CONTROL` write in
the C callback, and verifies that the callback branches to the helper.
An unrecognized framework source or an unsafe compiled handoff fails the
build check.

## Verification completed

- The DFU regression suite passed all 10 tests. It compiles Cortex-M4
  fixtures with `-Os`, `-Oz`, and `-Oz` with LTO. The Cortex-M emulator
  reproduces the original invalid stack access and verifies the fixed PSP
  and MSP caller paths, retained peer bytes, and handler exception frame.
  Tests also reject damaged or bypassed helpers and partially patched
  framework sources.
- Current standard and unified-LoRa-OTA RAK4631, Heltec T096, and Heltec T114 application builds passed
  their compiled Bluetooth DFU handoff check. These are build results;
  they do not establish physical Bluetooth transfer success.
- Existing identity/settings recovery, common radio persistence, and
  companion primary radio persistence suites passed all 7 tests.
- The compiled CLI settings suite passed all 9 tests, including the
  four-field radio response expected by the setup application.

The CI regression requires both the ARM compiler and Cortex-M emulator;
missing dependencies must not silently turn qualification into skipped
tests.

## Installing the fix on an affected application

An already installed affected application may fail before it can enter
Bluetooth DFU. Install an application containing this fix once through USB
UF2, or force the board into hardware DFU and use the matching application
package. Use the board's supported recovery entry procedure. Installing a
new bootloader does not replace the unsafe callback in the application.
OTAFIX recovery 2.4.12 adds a narrow fault fallback for this legacy callback:
when the forwarded HardFault occurs with the B1 Bluetooth DFU request marker,
it sets A8 and resets directly into BLE DFU without touching the broken stack.
Other faults keep their existing halt behavior. The unchanged 1.17.1.7 app
was physically observed reaching DFU through this fallback. This supplies
an alternative to USB application installation when the corrected bootloader
has already been installed; complete application transfer is recorded below.

The recovery bootloader is a temporary bridge for bootloader migration.
Complete migration to the normal physical-board bootloader according to
the recovery release instructions. An `R_` bootloader version is not itself
evidence that Bluetooth DFU is disabled.

## Separate setup-page and settings report

The reporter's first application install produced setup-page errors, while
the same application worked after an erase UF2 and reinstall. Application
UF2 installs normally preserve the application's filesystem. The standard
MeshCore erase firmware formats both InternalFS and ExtraFS, which changes
stored identity and preferences.

That result is consistent with a retained-state problem, but it does not
identify which setting, file, or client state failed. The original state
was lost after the erase, and the exact setup-page error was not recorded.
The Bluetooth handoff regression does not prove the cause of that earlier
setup failure.

The old app also appends `,preamble=32 (auto)` to `get radio` on this
test device. Current firmware restores the four-field radio reply expected
by the official setup app (commit `ca23d38e`). Its compiled CLI settings
regression checks this compatibility contract. This is another concrete
older-application compatibility issue, although the reporter's original
setup-page error was not captured and cannot be attributed conclusively.

Current firmware already includes truncated preference checks, bounded
strings, non-finite radio-value sanitization, durable identity retries, and
filesystem startup recovery. The 7 passing settings tests qualify those
existing protections. This Bluetooth fix adds no automatic wipe and does
not require an erase as its installation step.

## Hardware testing

### Published recovery baseline

On 2026-10-01, RAK4631 USB serial `9AB3B64C641BA927` ran the exact reported
`v1.17.1.7-halo-keymind-cascade-dev-2d03e098` application and published recovery
`R_0x02040BFF` (2.4.11). Nordic nRF Connect 4.24.3 on a second LG phone running
Android 5.1.1 attempted the fixed application ZIP. It failed before payload
transfer: the graph stayed at zero, the initial opcode disconnected, repeated
GATT 133 reconnect errors followed, and the device later answered `ver` with
the unchanged application. No RAK DFU advertisement was seen in a later scan.
USB data remained connected for this baseline.

### Bootloader fallback with the unchanged old application: PASS

The final recovery qualification image uses packed test version `0x02040CFF`,
production-length text `R_v0.11.0-OTAFIX2.4.12`, and bootloader CRC `5B8F3E90`.
It is a development qualification image, not the tagged production artifact.
The combined serial DFU ZIP installed it, then USB UF2 restored the unchanged
reported 1.17.1.7 application. Both identities were checked before retrying.

At 16:57:51 local time Nordic requested the same application ZIP. The
bootloader advertised `4631_DFU` at the original `C3:C6:A8:FC:AD:A6` address
about 11.7 seconds later. Nordic reconnected automatically, transferred the
531,708-byte application image from the 532,510-byte ZIP at about
2.2 kB/s, and activated the application at 17:02:19.
Afterward USB CLI reported `v1.17.1.8-ble-dfu-test (Build: 01-Oct-2026)` and
`OTAFIX2.4.12`. USB data was connected throughout this test.

No erase firmware was used. Seven queried values retained identical digests:
name, TX power, latitude, longitude, frequency, airtime factor, and public
identity. The radio tuple also stayed `869.6179809,62.5,8,5`; its old digest
exactly matches the new tuple plus the old preamble suffix. The differing raw
radio reply is the intended setup-client compatibility fix, not lost settings.
These are checks of the queried fields, not a dump of the entire filesystem.

The older application lacks a hash-bound EndF trailer. The installed recovery
bootloader safely refused its USB bootloader updater while that app was valid,
because it could not prove the staging scratch range was unused. This guard
is unchanged. The combined serial/Bluetooth DFU ZIP supplies the supported
installation path; permissive image identity policy does not disable flash
bounds or live-application staging safety.

### Fixed application through MeshCore Open

Pending on the second phone. The current Android legacy Open build
9.5.5/code 26 reached the Bluetooth updater, but `Enable radio updater`
rejected a selected route's hash width before sending its command. Open
commit `03b0d707` preserves each supported route's own width and rejects
malformed routes before sending. Its 81 focused tests passed, including
13 new tests through the real route preparation and command path.

The corrected API 21/ARMv7 Open build 9.5.5/code 27 was installed with
the phone's pairing data retained. Its SHA-256 is
`5a3a2f83299f1d4e27f242680335494d0ac49db5f8fa3e2ee8b71902f1924d33`.
The second phone disappeared from the VM's USB inventory during USB
re-enumeration before a completed Open transfer could be recorded. The
automatic USB configuration watcher was stopped. Record transfer completion,
installed version, USB power/data state, and restored radio state after
reconnecting that phone before claiming an Open physical pass.

### Hardware restored while the phone test is pending

The RAK4631 was returned to the published normal 2.4.10 `auto` bootloader
and the fixed `v1.17.1.8-ble-dfu-test` application. The ordinary application
has no `EndF` marker, so its bootloader UF2 replacement was safely refused;
the combined normal DFU ZIP and application UF2 supplied the working path.
No erase firmware was used.

A supplemental Linux Bluetooth check reached the application's DFU service
revision `0100`, requested handoff, and reached `4631_DFU` revision `0800`
at the same Bluetooth address. It then requested a return to the application.
After subscribing to control notifications on the bootloader connection,
the exit request returned the node to the application. Final CLI queries
confirmed the normal 2.4.10 bootloader, fixed application, saved radio tuple
`869.6179809,62.5,8,5`, and all seven unchanged settings digests. USB data
was restored. This checks the restored node's Bluetooth entry and exit;
it is not an Open transfer.
