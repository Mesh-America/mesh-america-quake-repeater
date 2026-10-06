# Battery charge voltage

The `charge.voltage` commands change the battery charger's constant-voltage
target on supported boards. They are available through the shared text CLI in
the companion, repeater, room-server, sensor, and secure-chat roles. They do not change the
battery voltage display, low-voltage shutdown, battery chemistry, or charge
current.

```text
get charge.voltage
get charge.voltage.options
set charge.voltage 4.1
```

Values are in volts. Query the options first: supported targets depend on the
PMU fitted to the board. The firmware rejects values that the detected PMU
cannot represent; it does not round them to a supported target.

On T-Beam boards, a successful change is saved in NVS and reapplied after a
restart. The firmware reads the PMU setting back before reporting success.
Boards without a saved setting retain their existing startup behavior: the full
PMU driver sets 4.2 V, while the compact classic T-Beam observer driver leaves
the charger setting untouched. A failed hardware write, readback, or preference
save is reported as an error.

If the saved target cannot be read, is invalid, or cannot be restored, startup
does not overwrite it with a default target. `get charge.voltage` reports the
live charger voltage with `(boot restore failed)`. A successful saved change
clears that warning. This cannot guarantee restoration while the PMU or storage
is failing, but it avoids silently resetting a saved lower target to 4.2 V.

## Supported boards

| Board family | Detected PMU | Charge targets (V) |
| --- | --- | --- |
| LilyGo T-Beam SX1262 or SX1276 | AXP192 | 4.10, 4.15, 4.20, 4.36 |
| LilyGo T-Beam SX1262 or SX1276 | AXP2101 | 4.00, 4.10, 4.20, 4.35, 4.40 |
| LilyGo T-Beam S3 Supreme SX1262 | AXP2101 | 4.00, 4.10, 4.20, 4.35, 4.40 |

Targets above 4.2 V require batteries rated for the selected charge voltage.

The classic T-Beam driver detects the fitted AXP192 or AXP2101. Radio type does
not determine which PMU is present. T-Beam 1W uses a different power design and
does not support this setting.

Neither AXP192 nor AXP2101 supports a 3.65 V target. The lowest supported target
is 4.10 V for AXP192 and 4.00 V for AXP2101. These PMUs cannot be configured as
LiFePO4 chargers by changing this setting.

## Heltec Mesh Solar

Mesh Solar reports `charge.voltage` as unsupported because its CN3795 charger's
constant-voltage target is set by hardware. Heltec supplies separate Li-ion
(`I`) and LiFePO4 (`F`) hardware versions, with 4.2 V/cell and 3.6 V/cell charging
respectively. Cell-count soldering and switches must also match the battery
configuration. A software battery-type setting does not convert one hardware
version into the other. See [Heltec's usage guide](https://wiki.heltec.org/docs/devices/open-source-hardware/nrf52840-series/mesh-solar/usage-guide)
and [MeshSolar datasheet, sections 4.1 and 4.4](https://resource.heltec.cn/download/MeshSolar/datasheet/MeshSolar_V1.0.0.pdf).

The BQ4050 on this board is a battery gauge and protection controller. Its
`ChargingVoltage()` is a requested voltage for a compatible smart charger. The
pinned Mesh Solar library calls that parameter `eoc`, but writing it does not
change the CN3795's voltage-feedback circuit. Valid charge termination also
requires the charging current to taper, so lowering `eoc` alone does not create
a reliable lower-voltage charge cutoff. Charge-overvoltage protection is a
separate safeguard, not the charger's normal constant-voltage target. See
[TI's BQ4050 technical reference manual, sections 4.5, 4.6, and 4.11](https://www.ti.com/lit/pdf/SLUUAQ3).

These commands do not write Mesh Solar's BQ4050 data flash or change its battery
type, protection limits, cell count, or charge-FET configuration.

## Battery profiles

The nRF52 `battery.profile`, `battery.full`, and `battery.empty` settings control
voltage-based reporting and protection. They do not change any charger target.
See [Battery profile commands](cli_commands.md#configure-nrf52-battery-protection).
