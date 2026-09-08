# XIAO Bluetooth stealth hardware validation - 2026-09-07

Historical command syntax: the initial run used stealth as a MAC mode.
Current firmware uses the independent `bluetooth.stealth on|off` flag instead
and does not migrate that development mode. See [current commands](cli_commands.md)
and the independent-flag follow-up below. Each observation applies only to
the exact artifact listed in its section.

This is a hardware observation report, not an all-board or phone qualification.
The test host was the MercerWoodMesh Raspberry Pi Zero 2 W, accessed remotely
over Tailscale. Tests used its built-in Bluetooth adapter, not USB resets or
hub power switching. Local timestamps below use America/Los_Angeles.

## Exact target and firmware

- Board: Seeed XIAO nRF52840; application name `MeshCore-4610BBD2`.
- Factory/bootloader address: `E5:C3:A8:B0:60:66`.
- Fresh stealth test address: `DC:8D:5E:45:89:6F`.
- Bonded test central: Mercer Pi, public address `B8:27:EB:F9:6E:8E`.
- Environment: `Xiao_nrf52_companion_radio_ble`, supported build wrapper,
  target radio preset, default profile, GCC 14.2.1.
- Firmware: `dev-stealth3-4b400ea5`, including the uncommitted Bluetooth
  identity changes on top of `4b400ea5`.
- Application ZIP SHA-256:
  `acdce0af2334349c6e0a5786db5525b00d19befef340411d2e99008ce4d316ae`.
- Linked RAM: 183,232 / 237,568 bytes; flash: 616,504 / 708,608 bytes.

The application was installed with Nordic Legacy BLE DFU. The tool verified
the exact ZIP hash, bootloader advertisement and live DIS model
`XIAO nRF52840` before transmitting 616,584 application bytes. Target image
validation and target-initiated activation disconnect passed. The transfer
reported about 2,223 bytes/second (about 277 seconds for payload transmission).
Authenticated MeshCore device queries subsequently returned protocol 14,
board `Seeed Xiao-nrf52`, and the expected unique test-version prefix.

## Observed results

| Check | Result and evidence |
| --- | --- |
| First-pair discovery | `set bluetooth.mac stealth` saved a new random-static address; reboot returned that exact address with the normal name and Nordic UART advertisement. |
| First authenticated pairing | The Pi received a passkey request and completed pairing. BlueZ reported both Paired and Bonded. MITM-protected Nordic UART notifications and real command/reply exchanges worked at MTU 247. |
| Pairing transition keeps the session alive | The initial connection returned `stealth; bonded-peer-only advertising`, remained usable for five more seconds, and answered another command without disconnecting or pairing again. |
| Advertising after disconnect | A public-address passive scan captured `ADV_DIRECT_IND` from the exact target, with advertising data length zero. The capture contained no undirected advertisement or scan response from that address. |
| Bonded reconnect | Subsequent direct connections by saved BlueZ device identity succeeded without a new passkey, including live version, core-statistics and Bluetooth-mode replies. |
| Warm reboot persistence | Two commanded reboots retained the address and saved bond. Directed advertising was captured after reboot, followed by authenticated reconnect. Device uptime decreased from 61 seconds before the second reboot to 35 seconds at the next query; core error flags were zero. |
| Slow advertising interval | A successful bonded reconnect occurred about 61 seconds after reboot, beyond the 30-second fast-advertising interval. |
| Reopen pairing | Setting `stealth` again from an existing bonded connection generated a new address, and the next boot allowed a fresh first pairing. |
| Restore default | `set bluetooth.mac default` plus reboot restored `E5:C3:A8:B0:60:66` and normal discovery. Fresh PIN pairing, version/core-statistics queries and repeated `factory address (default)` replies passed. The bench target was left in this discoverable mode. |

The newly completed pairing reaches Bluefruit's secured callback before its
bonded flag is necessarily ready. Recording the completed pairing in the
pair-complete callback as well, waiting for the deferred bond write, and
deferring identity-list reconfiguration until disconnect are covered by this
fresh-pair hardware run. Static source contracts also check those paths.

The binary reboot command can reset the target before BlueZ receives its ATT
write acknowledgement. One initial harness run reported `Unlikely Error`
after successful pre-reboot commands. Later checks require an observed
disconnect, a live post-reboot query and decreased device uptime; they do not
treat the write exception or tool exit code alone as a successful reboot.

## Discovery and DFU cautions found during testing

An ordinary BlueZ discovery scan used a temporary random local address and
did not show the directed target. A passive scan using the Pi's public
identity did show it. Reconnection must use the saved peer/device identity;
absence from an ordinary scan is not proof that the node stopped working.
Conversely, BlueZ can retain a cached name after pairing, so a displayed name
is not proof that the name is still being advertised. The packet-type and
zero-length-payload capture is the relevant evidence here.

The existing DFU handoff helper assumed the application and bootloader shared
one address. That assumption is false with a custom application address:
the authenticated handoff worked, but the helper timed out looking for DFU
at the application address. A fresh exact-address scan found the known
factory-address `XIAO_DFU` instead. An old factory-address host bond also
caused the first DFU service-discovery attempt to disconnect; clearing only
that old lab record allowed DFU. No bootloader code was changed for this test.

An earlier application-address host pairing record was also removed before
its saved stealth state was known. A direct, known-address connection from
the same Pi identity allowed fresh PIN pairing and protected commands again.
This does not prove that an arbitrary replacement phone can rediscover or
recover a stealth node after forgetting its bond.

## Remaining hardware gates

- True cold boot with all XIAO power sources, including battery, disconnected.
  The XIAO reported a battery voltage and did not enumerate as USB on the Pi;
  a Pi-only reboot or power cycle would not prove this gate.
- Unused-boot retention with `random-after-connect`, using a reboot trigger
  that does not itself authenticate over BLE. The policy has native tests;
  the remote BLE reboot command cannot prove this hardware gate.
- Android and iOS bonded reconnect, including a phone changing its resolvable
  private address, and direct-connection behavior in the actual MeshCore app.
- Rejection of a connection from a second, unbonded physical central.
- ESP32 Bluedroid and NimBLE hardware. Those use allowlisted minimal
  advertising rather than nRF52 directed advertisements.
- Node-side missing/corrupt bond and failed settings/bond-write fault injection.

## Repeatable regression procedure

1. Record the exact board, application version, ZIP hash, local/remote BLE
   identities and original Bluetooth setting. Keep a working recovery path.
2. Set the desired custom or random MAC, enable `bluetooth.stealth on`, reboot,
   and capture normal discovery before pairing.
3. Pair once. Require a stored bond and successful protected MeshCore commands,
   then keep the original session open and issue another command.
4. Disconnect. Capture the actual advertising type and payload with an
   appropriate receiving identity; do not use cached scan names as evidence.
5. Reconnect by the saved peer without another PIN and exchange commands.
6. For custom and saved-random addresses, repeat `bluetooth.stealth on`, reboot
   twice, and verify unchanged identity/bond, decreased uptime and live
   commands. Include a reconnect after the fast-advertising period ends.
7. Separately remove all target power and repeat the persistence checks.
8. Test `bluetooth.stealth off`, then `on`, as a pairing reset, and `off` as
   the exit from stealth. Verify live discovery, pairing, commands and an
   unchanged MAC policy. Changing the address to `default` is a separate step.
9. With each rotating MAC policy, verify that its rotation trigger still
   works, stealth stays enabled, and the new address permits fresh pairing.
10. Repeat relevant gates for a phone with address privacy and each BLE backend.

Raw VM-side logs, the exact artifact and bounded test helper are in
`/home/mesh/mercer-stealth-validation.jUDW0v/`. Raw Bluetooth captures are
local diagnostics and should not be published without privacy review.

## Mercer crash capture

During this run the Pi used its existing `dwc_otg.speed=1` full-speed USB
configuration. Kernel and health logs were streamed to this VM. No new kernel
errors or Pi lockup were observed during these tests; that does not establish
the cause of the earlier lockup.

The live test streams and all temporary scans were stopped at approximately
22:56 PDT. Journald remained active, the restore service remained enabled,
and the test XIAO was disconnected in default mode. Disk journals occupied
about 4.9 MiB at the final check.

At 22:35 PDT, temporary persistent journaling was enabled with a 16 MiB
configured disk-use limit, 2 MiB journal files, one-day retention and a
30-second normal sync interval. Recent buffered messages can still be lost
in a sudden failure. The original `Storage=volatile` configuration is intact.

`mercer-crash-capture-restore.service` is enabled for the next Pi boot. It
checks the armed boot ID, removes only the unchanged managed override,
switches journald back to RAM and leaves the old disk journals for collection.
Its same-boot no-op guard and unit syntax passed. The next-boot restoration
has not yet been exercised; no Pi crash or reboot was deliberately induced.

## Independent-flag follow-up - dev-stflag

The same XIAO and Pi were used later on 2026-09-07 to test the separate
`bluetooth.stealth on|off` flag, with no development-mode migration. This run
used `Xiao_nrf52_companion_radio_ble`, target radio preset, default profile,
and firmware `dev-stflag-4b400ea5` with the uncommitted flag changes.

- Application ZIP SHA-256:
  `48fc0ff2c716281771f8b525c62a0015c7605b07e7c513ab854c8b3ff3113f42`.
- Linked RAM: 183,232 / 237,568 bytes; flash: 617,192 / 708,608 bytes.
- Nordic Legacy BLE DFU verified the exact target, hash and model, transferred
  617,272 application bytes at a reported 3,522 bytes/second, passed target
  validation, and observed the target activation disconnect.
- Protected live device queries returned `dev-stflag-4b400ea5`, protocol 14,
  and `Seeed Xiao-nrf52`; every queried core error-flags value was zero.

| Check | Observed result |
| --- | --- |
| Default and rejected input | Initial mode was factory address with stealth off. `set bluetooth.mac stealth` and `set bluetooth.stealth maybe` returned errors, leaving both settings unchanged. |
| Custom plus stealth | `D2:27:5A:40:06:99` advertised normally before first pairing. Fresh PIN pairing, stored bond, protected commands, and a five-second held session passed with stealth on. |
| Repeated on and warm reboot | Repeating `set bluetooth.stealth on` retained the paired state. After reboot, the same custom address accepted protected commands without another PIN. Uptime decreased from 84 to 67 seconds. |
| Actual advertising after reboot | A public-address passive capture showed `ADV_DIRECT_IND` for the custom address, data length zero, and no undirected advertisement or scan response from that address. The scan was explicitly disabled afterward. |
| Off preserves custom address | `set ble.stealth off` and reboot restored normal discovery at the same custom address. A live connection returned stealth off and the unchanged custom policy. |
| Saved random plus stealth | `F2:2E:E5:65:18:5E` passed first pairing and held commands. After reboot, it retained its address, saved-random policy and stealth bond; protected reconnect needed no PIN. Uptime decreased from 55 to 30 seconds. |
| Random-after-connect plus stealth | Selecting this policy kept stealth on and reopened pairing at `C7:FD:29:44:4F:3E`. Pairing produced both bonded-peer-only status and an armed next-boot rotation. Reboot changed the address to `F5:F3:89:B7:B5:26`, where normal discovery, fresh pairing and protected commands passed with stealth still on. |
| Random-every-boot plus stealth | The first boot used `F9:B2:03:DD:CC:43`, completed fresh pairing, and answered commands with stealth on. The next commanded reboot advertised `F8:C7:C0:96:1E:00`; fresh PIN pairing and protected commands passed again with the rotating policy and stealth on. |
| Restore the bench target | Setting the MAC to `default` kept stealth on until the separate `set bluetooth.stealth off`. After reboot, factory-address discovery, fresh PIN pairing and protected commands confirmed default MAC and stealth off. The obsolete factory-address host bond was replaced during this final pairing. |

These checks used actual encrypted BLE connections at MTU 247, not scan
sightings alone. Two first-pair harness attempts stopped before connecting
because their unpaired BlueZ discovery object no longer existed. A fresh
bounded scan immediately followed by pairing was used for retries; this was
not a firmware GATT command failure. Reboot-write/disconnect races were
accepted only with an observed disconnect and subsequent live device checks.

Local automated verification passed 39 native cases, 32 source/persistence/UI
contracts, and 11 real-browser cases. Supported-wrapper builds passed for
XIAO nRF52, XIAO C3, M5Stack Unit C6L and XIAO S3 WIO Full Companion, covering
nRF52, ESP32 NimBLE and ESP32 Bluedroid integration. The contracts and browser
suite are included in the unit-test workflow; a browser must be available for
the optional browser suite to execute instead of skip.

Exact artifacts, build logs, command logs and the private packet capture are
in `/home/mesh/bluetooth-stealth-flag.ApLB8o/` on the VM. The remaining hardware
gates above still apply; these results do not qualify every board or phone.

At 23:42 PDT the XIAO was disconnected in normal discoverable mode. The Pi
retained the same boot ID throughout, remained responsive, and had no new
kernel messages in the streamed log. Journald was active, the next-boot
volatile-log restoration service was still enabled, and disk journals used
about 5.9 MiB. No USB reset, Pi reboot, or target battery removal was used.
