<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/solarxiao_advanced_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# SolarXiao Advanced carrier profile, 2026-10-21

The older SolarXiao 2W Advanced already supplies battery voltage and processor
temperature through XIAO self telemetry on channel 1. This change adds no new
physical measurements. It adds an explicit saved carrier selection, capability
reporting, live self-reading CLI aliases and guidance to existing history.

The published [Advanced Standard schematic](https://github.com/wehooper4/Meshtastic-Hardware/blob/main/XaioSeries/SolarXaio/Advanced/Standard/Schematic_SolarXaio_ADV_2025-10-23.pdf)
uses a BQ24650 analog charger. It has no INA monitor or digital charger
interface; status LEDs, charger NTC and analog setpoints are not connected to
XIAO measurement/control inputs. Firmware cannot recover panel V/I, battery
current/power, battery temperature or charger flags from that design.

Both existing `solarxiao_33S_repeater` Full and Reduced packages built and
passed package, capability and runtime memory checks. Native host fault tests
passed under ASan/UBSan. These are build/host results, not hardware acceptance.
No firmware was installed on SEA Sherwood, which the user confirmed is
unreachable. Its exact installed target, bootloader and physical revision were
not verified. The earlier Mercerwood MPPT bench report does not qualify this
new image on physical hardware.

See the [controls guide](../solarxiao_power.md) and
[machine-readable validation record](solarxiao_advanced_2026-10-21.safe.json).

## Qualified source and packages

| Item | Result |
| --- | --- |
| Application source | [`de1bb0f2e6a37b02f1a9f0995ea539c818c3abe9`](https://github.com/mikecarper/MeshCore/commit/de1bb0f2e6a37b02f1a9f0995ea539c818c3abe9) |
| Version | `v1.18.0.1-halo-keymind-cascade-dev-de1bb0f2` |
| Target / hardware ID | `solarxiao_33S_repeater` / `solarxiao_33S`, unchanged |
| EndF OTA target | `0x3caf966e`, unchanged |
| Full application | 597,816 bytes; body hash `C5339ADF076AEC89` |
| Reduced application | 567,756 bytes; body hash `68D86AA255060031` |
| Full memory check | PASS: 150,584 internal bytes available; 76,960 required |
| Reduced memory check | PASS: 152,232 internal bytes available; 76,960 required |
| DFU ZIP, UF2, linked capabilities | PASS for both profiles |
| Linked carrier commands and history | PASS for both profiles |
| Source changes to RF/PA, bootloader, flash layout or battery protection | None |

Both packaged applications retain the native MPPT marker and contain the
Advanced selector, BQ24650 capability text, live XIAO-reading response, history
guidance and unavailable-measurement explanation. Application body hashes and
EndF identity fields were checked independently. The build's artifact manifest
hashes matched every published local package, UF2 and capability file.

These packages contain compiled LoRa/Bluetooth update support. No LoRa OTA,
boot, radio forwarding, charging or electrical test was performed for this
image. Future deployment requires checking the destination's installed target
and matching board/storage-aware bootloader; no remote update was attempted.

## Host coverage

The following checks passed:

- 11 new carrier test methods, including the actual adapter, checked atomic
  writer and filesystem presence boundary: explicit/default selection, restart,
  corrupt/wrong-size/unreadable records, metadata errors, short writes, failed
  rename, corrupt publication, ambiguous public readback and explicit recovery.
- Every Advanced/unconfirmed native service, read, write, action, telemetry and
  voltage-history path produced zero native bus calls. Live XIAO ADC/MCU reads
  remained available. Switching back to MPPT reloaded retained charger overrides
  and restored native readings/telemetry.
- CLI parser boundaries, reply canaries for capacities 1..157, nonfinite/missing
  readings and history-included/omitted builds. The role passes its actual
  compiled history capability to the adapter.
- Three existing MPPT test methods, covering eight core scenarios, real
  transport/atomic settings boundaries and telemetry permissions/channel order.
- Six existing XIAO battery/startup/GPIO safety checks, including negative
  controls for unsafe historical GPIO sequences.

Reproduction:

```sh
python3 -m unittest discover -s test -p 'test_solarxiao*.py' -v
python3 -m unittest discover -s test -p test_xiao_battery_safety.py -v
bash build.sh build-firmware solarxiao_33S_repeater \
  --firmware-version v1.18.0.1-halo-keymind-cascade-dev \
  --radio-preset usa-cascadia --profile cascade
```

PlatformIO ran once at a time; the build entry point produced Full and Reduced
sequentially. Local packages and logs are retained under
`/home/mesh/hwtest/solarxiao-advanced-20261021/`.

## Using the profile after a compatible update

```text
set solar.board advanced
get solar.board
get solar capabilities
get solar readings
get solar history
```

The operator selects the board. A missing/unpowered I2C device never identifies
Advanced automatically. The absent-record default remains MPPT for existing
installations; a failed presence query must yield a complete valid record or
block native access. The separately stored selection does not alter existing
charger overrides. Selecting MPPT again re-enables and reloads those overrides.

Channel-1 voltage and MCU temperature are unchanged. Voltage/temperature history
remains the existing 30-minute, seven-day RAM history and resets on reboot.
The MCU temperature is not battery temperature, and a voltage trend does not
measure charge current, solar power or charger state.
