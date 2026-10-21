# SolarXiao MPPT and battery controls

SolarXiao Repeater firmware includes a native INA260 battery monitor and LTC4162
charger interface in Full and Reduced builds. Use USB CLI or the authenticated
administrator CLI over LoRa. Ship mode and
saved-policy reset require local USB. Commands do not change RF settings.

Start with:

```
get mppt
get mppt battery
get mppt power
get mppt alerts
get mppt saved
get mppt fields 0
```

`fields` returns three names per page with `rw`, `ro` or `locked`. Increment the
page to enumerate the register interface. `get mppt <field>` returns units and
the raw register. `get mppt raw 0x43` reads a documented register; arbitrary
register writes are not exposed. `nan` in a summary means unavailable, not zero.

## Identity and readings

The carrier bus uses SDA P0.09 and SCL P0.10. INA260 at `0x40` must match its TI
manufacturer and device IDs. Its signed current, voltage and power readings do
not require charger input power. The driver does not reset/configure INA260.
LTC4162 at `0x68` uses little-endian SMBus words. Access normally requires power
at SOLAR/VIN; USB alone can leave the charger unavailable.

`get mppt info` reports the chemistry/profile code, live cell count, last observed
nonzero cell count, MPPT, JEITA, charger state and telemetry validity. The actual
bench board identified as FST (chemistry code 6); this distinguishes it from
FAD, FFS, Li-ion and SLA variants. The ID does not uniquely identify the M suffix
or package/temperature grade. Cell count comes from hardware straps; zero means
unknown while the charger is inactive. Software cannot change chemistry/cells.

Readings cover battery/input/output voltage, signed battery/input current,
charger die and modeled NTC temperature, battery series resistance, charge/CV/
absorb timers, JEITA region, actual DAC settings, system/status bits and all three
alert banks. A retained ADC bank is not presented as live while telemetry is off.
Battery ADC voltage/resistance need a currently valid cell count. Questionable
resistance and an open/disconnected NTC return unavailable in the summaries.

## Settings on the 4S FST carrier

Use `set mppt <field> <value>`. Booleans accept `on` or `off` only.

| Fields | Behavior |
| --- | --- |
| `mppt.enabled` | Enable automatic solar maximum power tracking. |
| `charge.enabled` | Suspend/resume charging; does not disconnect the battery or system output. |
| `telemetry.force`, `telemetry.fast` | Force the charger ADC on, or use fast telemetry. These affect power consumption. |
| `input.limit_ma` | Input current limit; rounds down to the hardware step, never above the request; maximum request 3200 mA. |
| `input.minimum_mv` | Manual input-voltage floor; MPPT must be off. Rounds up in 140.625 mV steps, maximum request 35000 mV. |
| `jeita.enabled` | Select the fixed multi-region JEITA profile or basic temperature-qualified manual targets. |
| `charge.current_ma`, `charge.cell_mv` | Manual targets require JEITA off. Current rounds down in resistor-dependent steps, up to 3200 mA. This 4S board interface limits voltage requests to 3412.5..3600 mV/cell in 12.5 mV steps. |
| `thermal.start_c`, `thermal.end_c` | Die thermal regulation thresholds, -40..125 C; start must remain below end. |
| `termination.enabled`, `termination.current_ma` | C/x termination switch and nonnegative current threshold. |
| `termination.cv_seconds`, `termination.total_minutes` | 16-bit safety timers; zero disables the corresponding timer. |
| `alert.*` | Voltage/current/die/NTC/resistance thresholds and enabled alert masks; use field names/units from `fields`. |

FST locks the six JEITA thresholds, regional current/voltage values, recharge
threshold and absorb voltage/time. These remain readable. Manual target
registers are continuously overwritten by JEITA when JEITA is on; read actual
`dac.*` fields to see the active regulation targets. Basic temperature-qualified
charging still uses the fixed outer temperature limits when JEITA is off.

All configuration writes require a fresh FST identity and a live cell count of
4 or unknown. Other variants remain readable but cannot receive this board's
saved settings. Every setting uses a masked register update and verifies
readback before success. Unrelated bits are preserved; one-shot BSR is not
replayed by configuration writes. A failed write/save attempts to restore the
previous field and reports whether rollback was verified.

## Saving and actions

Successful settings save an explicit override in a versioned, CRC-protected
`/solar_power` record, using atomic file replacement plus public-file readback.
The board reapplies only saved overrides after restart or charger power loss,
with a five-second retry interval. It does not write default settings on first
boot. JEITA-owned targets are not repeatedly written while JEITA is enabled.
A failed/corrupt settings file blocks configuration saves and automatic replay.

- `mppt reload`: reload saved policy and retry applying it.
- `mppt forget`: remove saved register overrides; keep calibration and live chip settings.
- `mppt reset`: local USB only; reset saved policy/calibration to reference values,
  including recovery from a corrupt record. Live charger registers are unchanged.
- `mppt bsr run`: request one battery-resistance measurement; not saved.
- `mppt ship arm` / `mppt ship disarm`: local USB only; not saved. Arming takes
  effect when VIN drops below approximately 1 V and can remove system power.
- `mppt alerts clear limits|states|status <mask>`: clear selected latched alerts
  using write-zero-to-clear semantics; unselected/new alerts are preserved.

These actions acknowledge the request, not completion of charging, resistance
measurement or entry into ship mode. Read the corresponding status afterward.

## Conversion defaults and carrier revisions

The supplied [Standard schematic](https://github.com/wehooper4/Meshtastic-Hardware/blob/main/XaioSeries/SolarXaio/MPPT/Standard/Schematic_SolarXaio_MPPT_2025-10-23.pdf)
shows R5/RSNSI and R14/RSNSB at 10 milliohms, a 10 kohm NTC bias and a 10 kohm
NTC. It shows an L42M single-cell charger, so it does not independently confirm
component values on this 12 V FSTM revision. Defaults use those resistor values
and the LTC4162 reference thermistor beta of 3490 K. Readings identify the model
as `reference` until the corresponding calibration values are explicitly set.

Calibration settings, saved without changing hardware target registers:

```
get mppt cal.rsnsb_mohm
get mppt cal.rsnsi_mohm
get mppt cal.ntc_bias_ohm
get mppt cal.ntc_r25_ohm
get mppt cal.ntc_beta
```

Set these with the same `set mppt` syntax after confirming actual components.
Allowed sense resistance is 0.1..1000 milliohms, NTC/bias resistance 100..1000000
ohms, beta 1000..10000 K. The simple beta temperature model assumes an unpadded
NTC divider. It does not model series/parallel thermistor dilution networks.
Changing calibration changes units/conversions, not already saved register codes.
INA260 uses its integrated shunt and does not use these sense-resistor values.

## Telemetry channels

Carrier telemetry requires the environmental telemetry permission. Channel 1
remains the XIAO internal ADC; it is separate from the 4S carrier battery and its
existing startup/low-voltage policy is unchanged.

| Channel | Values |
| --- | --- |
| 2 | INA260 battery voltage, signed current, power |
| 3 | LTC4162 input voltage, signed current, computed nonnegative input power |
| 4 | Charger system output voltage |
| 5 | Charger battery ADC voltage and signed current |
| 6, 7 | Die temperature, modeled NTC temperature |
| 8, 9, 10 | Generic sensor integers: charger state, charge status, system bits |
| 11, 12, 13 | Generic sensor integers: limit, state and status alert masks |
| 14 onward | Optional environmental sensors, in discovery order |

Unavailable values are omitted. Voltage history reserves channels 2..5 and
marks unavailable samples invalid. The generic sensor scanner cannot claim
carrier addresses `0x40`/`0x68`; this prevents an INA219 driver from configuring
the INA260 and keeps carrier channels stable across profiles and power states.
No state-of-charge percentage or coulomb counting is inferred from voltage.

References: [SolarXaio hardware](https://github.com/wehooper4/Meshtastic-Hardware/tree/main/XaioSeries/SolarXaio),
[LTC4162-F Rev A](https://www.analog.com/media/en/technical-documentation/data-sheets/ltc4162-f.pdf),
[INA260](https://www.ti.com/lit/ds/symlink/ina260.pdf).
