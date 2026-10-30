# D7S earthquake sensor (RAK12027) integration

Status: experimental. The sensor path was hardware-tested on one board (RAK19007 + RAK4631 + RAK13302 + RAK12027 in slot A) in an earlier MeshCore-based build: telemetry was correct, repeater operation was normal, and stats requested while the unit was being shaken answered instantly. This Keymind-based Mesh America build is a port of that code. The RAK3401 image has since been run on hardware by its maintainer, though TX power has not been measured, so the IO2 and booster question below is open. The RAK4631 image for a RAK19003 base (the RAK10703 kit) is an alpha that has not been run on hardware: see its own hardware notes below.

The Omron D7S is handled like the other environmental sensors: `EnvironmentSensorManager` finds a device at its I2C address (0x55) during the boot-time scan, polls it, and adds its readings to telemetry. `ENV_INCLUDE_D7S=1` is set only in the Mesh America Quake Repeater environments (`MeshAmerica_Quake_Repeater_RAK3401` and `MeshAmerica_Quake_Repeater_RAK4631`, defined in `variants/meshamerica_quake/platformio.ini`); every other Keymind environment is unchanged. A board adds support by defining `ENV_INCLUDE_D7S=1` and handling a shared INT2 pin in `src/helpers/sensors/D7SBoard.h`.

The Quake Repeater image without a D7S attached carries one sensor-table entry that never matches; the I2C scan, telemetry and pin handling are unchanged. A D7S takes six consecutive sub-channels, so `MAX_ACTIVE_SENSORS` is 22 instead of 16 when it is compiled in.

## Behavior

- Detection happens once at boot: a device that ACKs address 0x55 is treated as a candidate. A sensor that is absent or busy at that moment is not picked up until the next reboot, and whether a D7S ACKs during its power-up calibration is not documented by Omron.
- Nothing is read for the first 4 s after detection (RAK's library waits about 4 s after power-up; the Omron specification only says the sensor enters normal mode at power-on). Then it is polled every 250 ms, and retried every 5 s after a failed poll. A candidate that never returns a valid state register (0 to 4) is never confirmed, so a foreign device at 0x55 only wastes the six channels, reporting health 0.
- Neither initialization nor telemetry writes calibration or clears stored history, and the firmware never commands self-test or offset acquisition. Reading the EVENT register is destructive (read-to-clear), so the driver keeps the flags itself.
- Telemetry requests use cached results and require environmental-telemetry permission. Readings older than 2 s are reported as unavailable; the event-flag channel is the exception (see below).
- The driver is portable (`D7S.h/.cpp`). `D7SWireTransport.h` adapts it to an Arduino `TwoWire` bus; reads use a repeated start (`endTransmission(false)`), as in the vendor library, but the on-wire result on the nRF52 core is unconfirmed without a bus capture.
- Interrupts are not used by the firmware. The driver has a `notify()` entry for them, but no variant wires INT1/INT2; polling is the only path. The sensor latches EVENT flags until they are read, so polling at 250 ms loses nothing while polls succeed. If an EVENT read fails after the address ACK the flags may already have been cleared, which is what bit 128 below reports.

## Telemetry

The D7S takes six consecutive channels, allocated after the sensors ahead of it, only when a candidate is present. Offsets are relative to its first channel.

| Offset / LPP type | Label | Meaning |
|---|---|---|
| 0 / digital input | Sensor health | 1 = recent successful read; 0 = unavailable |
| 0 / generic | Sensor state | 0 standby; 1 normal mode not in standby (primarily earthquake processing); 2 installation; 3 offset acquisition; 4 self-test. Omitted when unavailable. |
| 1 / generic | Live SI | Raw / 10 = cm/s (unit inferred from the stored register). Only while fresh and processing. |
| 2 / generic | Live PGA | Raw counts; the live scale is unresolved (see the measurement contract). |
| 3 / generic | Recorded events | Present once the sensor has answered or a failed read may have lost flags. Flags retained since the first successful poll: 1 significant shaking (the sensor's shutoff signal), 2 tilt, 4 self-test error, 8 baseline error; a bit mask, not a count. Bit 128 means an EVENT read failed and may have discarded flags the firmware never saw. Nothing clears these in firmware, so they last until reboot. Not freshness-gated: check the health channel. |
| 4 / generic | Stored SI | Latest stored record, raw / 10 = cm/s. May predate boot; cleared memory reads as zero. |
| 5 / generic | Stored PGA | Latest stored record, raw / 10 = gal (raw / 9806.65 = g). May predate boot. |

Stored values are fetched on the first successful standby poll and again after a non-standby state, a new shaking or tilt flag, or any failed poll. They are history, not a new-event notification: there is no age, event ID or timestamp. Offset 0 carries two records on one channel; a parser keyed by channel alone may keep only one. Apps need an agreed way to identify these channels; none exists yet. See [measurement definitions](d7s-measurement-contract.md). Do not label these values Richter magnitude, an epicenter or building damage.

## Hardware notes (RAK19007 + RAK4631/RAK3401 + RAK13302 + RAK12027)

Slot A was recommended by RAK's WisMap pin mapper (a screenshot, not re-fetchable): RAK12027 at 0x55 on I2C1 (SDA P0.13, SCL P0.14), INT1 on IO1, INT2 on IO2 (P1.02, Arduino pin 34). RAK's RAK12027 product page lists slots C-F only, and the RAK13302 already uses IO3-IO6, so slot A is the only free one on this assembly. The driver does not detect the slot.

The sensor's supply rail is unresolved. WisMap and the module pin table show VDD on the plain 3V3 rail; RAK's RAK12027 page says the module is powered from 3V3_S, controlled via IO2. IO2 is the base board's `EN` for 3V3_S, and the RAK19007 page says IO2 cannot be used as a sensor interrupt when 3V3_S is used. INT2 is an open-drain output.

On a RAK3401 the stock firmware drives IO2 high. That would fight INT2, so once a D7S is confirmed (first valid state read, never on the scan ACK alone) `d7sBoardOnConfirmed()` in `src/helpers/sensors/D7SBoard.h` releases IO2 to an input with the internal pull-up; other builds, and images with no D7S attached, keep IO2 driven high. This applies to a D7S in any slot. It is a deliberate exception to the rule used elsewhere in this code base that IO2 (the shared 3V3_S rail enable) is never released. Low-voltage shutdown still drives IO2 low. Nothing in this repository shows what happens while INT2 is asserted (power-up offset acquisition, earthquake processing): the enable can be pulled low, which may cut the sensor's own supply if it is on 3V3_S, and may affect the RAK13302 booster. Whether IO2 gates the booster is also unresolved: the variant comment inherited from the base target says it does, WisMap shows the RAK13302 using no IO2 or 3V3_S, and RAK's RAK13302 datasheet lists pin 6 as 3V3_S without stating its function. An earlier diagnostic build ran with IO2 as a plain input and INT2 active and the sensor communicated, which is indirect evidence only. Measure TX power with the sensor fitted at idle and while INT2 is asserted, and the sensor's supply voltage during offset acquisition, before treating either as verified.

## Hardware notes (RAK19003 + RAK4631 + RAK12027: the RAK10703 kit)

Status: **confirmed by a user test** on a RAK10703 kit, with the earthquake sensor in slot C; the maintainer separately ran the RAK4631 image on a RAK19007 with the sensor in slot D. The RAK10703 earthquake sensor kit is a RAK19003 mini base board, a RAK4631 core and a RAK12027 (D7S) in an IP65 Unify enclosure with a solar panel and an integrated antenna (the RAK10703-K kit has no battery; the RAK10703 solution is assembled and has one). The `MeshAmerica_Quake_Repeater_RAK4631` environment builds this combination, and also any RAK4631 on another WisBlock base with the sensor fitted. The kit ships with RAK's own firmware; this one replaces it. Facts below come from RAK's product page and datasheets, read on 2026-10-05, and from WisMap, read on 2026-10-29.

- **Slot.** The RAK19003 has two sensor slots, **C and D**, not A. The earthquake sensor is a double-width module and goes in **slot C**: WisMap labels the slots `SENSOR_C (double)` and `SENSOR_D` and offers the sensor only in C, and a user test on a RAK10703 kit confirmed it. (RAK's RAK19003 datasheet text says slot D takes 23 mm modules and slot C only 10 mm ones, which is wrong for the kit.) The firmware does not detect the slot.
- **Interrupts.** In slot C the module's INT1 is IO3 and INT2 is IO4 (in slot D they would be IO5 and IO6). The firmware does not use the interrupts (it polls), so the slot makes no difference to it.
- **I2C.** The sensor is on the base's I2C1 (SDA P0.13, SCL P0.14 on a RAK4631, as in the variant), at address 0x55.
- **Power and IO2.** The RAK19003 datasheet says IO2 is the enable for the 3V3_S rail, and that rail powers the RAK12027. Unlike the RAK3401 build above, **IO2 is not the sensor's INT2 here**, so there is nothing for it to fight. `d7sBoardOnConfirmed()` therefore does nothing on a RAK4631 and IO2 stays driven high, which keeps the sensor powered. Keymind's default RAK4631 peripheral mode (`gps-only`) would otherwise switch 3V3_S off when no GPS runs, and the firmware then skips the environment sensors when answering telemetry: that is what happened in 1.18.0.1, where the earthquake sensor and RAK1906 were missing from telemetry. From 1.18.0.2 the quake RAK4631 image holds the rail on (`MESHAMERICA_QUAKE_HOLD_SENSOR_RAIL`, see `WisBlockSharedPowerPolicy.h`), whatever `peripherals.mode` is saved.
- **Radio.** The RAK4631's SX1262 transmits at up to 22 dBm. There is no external amplifier as on the RAK3401 with a RAK13302, so range is lower.

Not verified: whether the D7S answers during its power-up calibration, and the live PGA scale (see the measurement contract). Do the same [hardware check](#hardware-check) as for the RAK3401 and report what you see.

## Other sensor modules: RAK1906 environmental sensor (BME680)

The RAK1906 is Bosch's BME680 on a WisBlock module: temperature, humidity, pressure and gas resistance. Both Quake images now detect it, in any sensor slot, on a RAK3401, a RAK19007 base or a RAK19003 base.

- **Why it did not work before.** Keymind's reduced-sensor trim, which both Quake images use to save flash, removes every optional environmental driver, including the BME680 (and so does each base environment). Nothing probed for the module, so it was never detected in any slot, with or without the earthquake sensor. PlatformIO emits every `-U` after every `-D`, so a `-D` in `platformio.ini` cannot bring the driver back. `variants/meshamerica_quake/quake_sensors.h` is force-included (`-include`) instead: it is processed after all command-line options, so its define wins and no Keymind-owned file changes.
- **What it reports.** One telemetry channel with temperature, relative humidity, barometric pressure, altitude (computed from pressure at standard sea level) and gas resistance. Gas resistance is a raw value in ohms; it is **not** an air-quality index. The firmware reads the sensor only when telemetry is requested, so it costs nothing while idle.
- **Not included: BSEC.** Bosch's BSEC library would add an air-quality index (useful for wildfire smoke), but the existing code samples it continuously, every 3 seconds, which is a steady power draw on a remote solar node, and its core binaries are under a separate Bosch click-through license (the Arduino wrapper is BSD-3) that someone should read before releases include it. A trial build costs about 37 KB more flash (60.4% to 64.9% on the RAK4631 image) and about 1.6 KB more RAM, so size is not the obstacle. Bosch also offers a 5-minute sampling mode that would cut the draw sharply; it needs a different BSEC configuration and a code change, and its real current draw has not been measured here. Neither has been tried on hardware.
- **Fit and wiring.** The module is 10 x 10 mm, so it fits any slot, including slot D of a RAK19003 (the single slot, which takes only 10 mm modules), next to the earthquake sensor in slot C. It takes power from the always-on VDD pins and uses only I2C1, not the switched 3V3_S rail or any IO pin, so it does not touch the IO2 question above. The firmware probes I2C addresses 0x76 and 0x77. The earthquake sensor is at 0x55, so they do not clash.
- **RAK19007 slot A.** On a RAK19007 the earthquake sensor in slot A puts its INT2 on IO2 (see the RAK19007 notes above), and the RAK4631 image keeps IO2 driven high. Put the earthquake sensor in slot D, not A, with that image. This is from the datasheets and code, not a hardware test.
- **Verified on hardware (maintainer report):** the RAK4631 image on a RAK19007 base, with the earthquake sensor in slot D and a RAK1906: all telemetry, including the RAK1906's, works. **Not yet run:** the RAK1906 on a RAK19003 base (the RAK10703 kit), and the RAK1906 with the RAK3401 image.

## Limits

- `Wire` on the nRF52 core has no timeout (unbounded waits, and the D7S has clock stretching enabled), so a device holding the I2C bus can stall the main loop, as with every other sensor on that bus. A bounded `Wire` in the core fork would fix this for all sensors and should be proposed separately.
- No channel alerts, saved alert destination, app changes, GRP_DATA schema or automatic channel labelling exist yet.
- Detection is boot-only; stored records have no provenance; the live PGA scale is unresolved.

## Hardware check

1. Record existing radio settings and confirm the companion matches them.
2. Flash the Mesh America Quake Repeater build and confirm login, stats and telemetry at rest: after about 5 s the health channel should read 1 and the state 0.
3. Move the enclosure: the live channels should appear while the state is 1; leave it still for over two minutes, then check that the stored channels show the record.
4. Measure TX power against the stock build, and the sensor's supply voltage, as described above.

## Files relative to Keymind Cascade

Added: `D7S.h/.cpp`, `D7SWireTransport.h`, `D7SBoard.h`, `variants/meshamerica_quake/quake_sensors.h` (re-enables the BME680 driver for the RAK1906), `SeismicAlert.h/.cpp`, `ClockFloor.h/.cpp` (in `src/helpers/sensors/`), `examples/simple_repeater/MyMeshQuake.cpp` (see [earthquake-alerts.md](earthquake-alerts.md)), `variants/meshamerica_quake/platformio.ini`, the tests `test/test_d7s*`, and these documents. Changed (small, to keep merging Keymind updates easy): the D7S block, table entry and loop hook in `EnvironmentSensorManager.cpp/.h`, the shutdown `pinMode` in `variants/rak3401/RAK3401Board.cpp`, the `D7S.cpp` and `SeismicAlert.cpp` entries in the native test filter in `platformio.ini`, a `SeismicReading` accessor in `SensorManager.h`, the version line of the owner-info response in `MyMesh.cpp`, and `ENV_INCLUDE_D7S`-guarded hooks in `examples/simple_repeater/MyMesh.cpp/.h` (a group-text sender split out of `sendRepeatersFloodText`, the loop call and the CLI branch).
