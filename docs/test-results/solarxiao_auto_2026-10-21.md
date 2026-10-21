# SolarXiao automatic carrier detection and Base support, 2026-10-21

SolarXiao repeater firmware now defaults to automatic carrier detection when
there is no saved selection. A verified INA260 identity enables MPPT support;
until then, the firmware reports self-only telemetry without guessing Base
versus Advanced. Existing saved manual selections retain their meanings.
Manual `auto`, `base`, `advanced` and `mppt` settings remain available.

Base needs no additional telemetry driver. The published
[Base Standard schematic](https://github.com/wehooper4/Meshtastic-Hardware/blob/main/XaioSeries/SolarXaio/Base/Standard/Schematic_SolarXaio_Base_2025-10-23.pdf)
uses a CN3791 analog charger with no digital interface or INA monitor. Its
battery connects to the XIAO BAT input; charge status drives an LED. Like the
older BQ24650 Advanced design, it provides existing XIAO battery voltage and
MCU temperature only. There are no new physical measurements for either board.
Base Lite publishes a README but no schematic; its exact wiring is not
independently qualified here.

Radio target selection stays separate. The published Base schematic specifies
E22-900M30S; the pictured 2W Advanced has M33S. The existing 30S/33S target must
match the fitted module. Charger detection does not change RF settings,
PA limits, hardware/OTA identity, bootloader, flash layout or battery protection.

## Qualified source and packages

| Item | Result |
| --- | --- |
| Application source | [`5c44324330a4b3a2e79059dbfa5e086d4cfc1e08`](https://github.com/mikecarper/MeshCore/commit/5c44324330a4b3a2e79059dbfa5e086d4cfc1e08) |
| Version | `v1.18.0.1-halo-keymind-cascade-dev-5c443243` |
| 33S OTA target / hardware | `0x3caf966e` / `solarxiao_33S`, unchanged |
| 30S OTA target / hardware | `0xb38ebf22` / `solarxiao_30S`, unchanged |
| Native host checks | 22 PASS: 19 carrier methods and 3 existing power methods; native harnesses use ASan/UBSan |
| XIAO startup/battery safety checks | 6 PASS |
| Full/Reduced DFU, UF2, linked capabilities, memory | PASS for both targets |

| Target | Profile | Application bytes | EndF body hash | Internal bytes available |
| --- | --- | --- | --- | --- |
| `solarxiao_33S_repeater` | Full | 599,132 | `7AB98467B6E3A468` | 150,576 |
| `solarxiao_33S_repeater` | Reduced | 569,136 | `217075127849EE7C` | 152,224 |
| `solarxiao_30S_repeater` | Full | 599,132 | `0C386CB1FC49608C` | 150,576 |
| `solarxiao_30S_repeater` | Reduced | 569,136 | `ACBB1554247BB0B5` | 152,224 |

Every memory check requires 76,960 heap/transient bytes. Both profiles in both
targets retain compiled LoRa/Bluetooth update support and telemetry history.
Independent package checks verified the application version, EndF body length,
body hash and target/hardware IDs. Package, UF2 and manifest file hashes matched.
All four applications contain the native power marker, verified/pending Auto
responses, Base/CN3791 and Advanced/BQ24650 descriptions, live self-reading
response and history guidance.

The first 30S dependency installation failed before compilation because of a
local disk quota. Reusing the identical inherited 33S dependency cache resolved
the build setup; the final 30S Full/Reduced pair passed. PlatformIO processes
ran sequentially throughout. Logs and packages are retained under
`/home/mesh/hwtest/solarxiao-auto-20261021/`.

See the [machine-readable validation record](solarxiao_auto_2026-10-21.safe.json)
for exact package/application/UF2 hashes and detection parameters, and the
[controls guide](../solarxiao_power.md) for commands and hardware limits.

## Detection and host acceptance

Auto reads only INA260 identity registers at carrier address `0x40`:
manufacturer `0xfe = 0x5449` and device `0xff & 0xfff0 = 0x2270`. Address ACK,
wrong identity, missing response and an incomplete second read do not enable
MPPT. No INA or charger configuration is written by detection.

The first probe occurs after startup initialization. Unverified detection
retries every five seconds, including across the millisecond timer wrap.
A positive identity is retained until reboot or a successful mode change;
temporary communication loss does not demote it. Before verification, the
adapter does not read the LTC4162, replay saved overrides or emit native carrier
telemetry/history. Self battery/MCU readings remain available.

The actual adapter harness verifies delayed discovery and reloads retained
charger overrides only on the transition that enables native access. A dedicated
long-uptime test first services manual MPPT at a low timestamp, disables it,
then detects Auto at `UINT32_MAX - 1000`: replay occurs immediately once, the
next check waits exactly five seconds across wrap, and a simulated charger
reset reapplies the override without redundant writes afterward.

Manual Base/Advanced and unconfirmed/corrupt selections make zero native bus
calls. Saved Auto restarts as unverified; original eight-byte manual MPPT and
Advanced records keep their exact meanings without being rewritten. Fault
tests cover metadata/read errors, wrong-size/corrupt records, partial writes,
failed rename, corrupt publication and ambiguous public readback. Explicit
successful selection recovers. Existing parser bounds, reply canaries, missing
readings, history feature propagation, core charger checks and telemetry
permissions/channel-order tests also pass.

## Deployment limits and commands

No firmware was flashed to any device in this run. No physical Auto detection,
Base/Advanced electrical measurement, boot/soak, radio forwarding or LoRa OTA
transfer was tested for this image. SEA Sherwood remains unreachable and
unchanged; its installed target and bootloader have not been verified. Earlier
Mercerwood hardware results belong to their named firmware revisions.

With no saved selection, Auto requires no setup. To replace a saved manual
selection after installing compatible firmware:

```text
set solar.board auto
get solar.board
get solar capabilities
```

Manual overrides use `set solar.board base|advanced|mppt`. When native access
becomes enabled, retained `/solar_power` overrides are reloaded. Fresh LTC4162
chemistry/cell-count checks still independently guard all charger writes.
