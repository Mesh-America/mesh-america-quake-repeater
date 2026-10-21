<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/solarxiao_power_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# SolarXiao MPPT and battery controls, 2026-10-21

The Mercerwood SolarXiao 33S repeater now has a native LTC4162-FST charger
interface and INA260 battery monitor in both Full and Reduced firmware.
All 75 named register fields were read on the board. Supported setting changes
passed live readback and persisted across a warm restart. The original charger
register values were restored and all test overrides/calibration flags cleared.
Three nonce-bound repeater forwarding tests passed at -6 dBm.

[Machine-readable acceptance record](solarxiao_power_2026-10-21.safe.json)
contains exact build identities, readouts, command replies, fault-test coverage,
RF samples, cleanup and limits. See the
[SolarXiao controls guide](../solarxiao_power.md) for commands, units, permissions,
persistence, calibration and telemetry channels.

## Qualified firmware and hardware

| Item | Result |
| --- | --- |
| Source | [`ea8176ddc6b2caa7e52f8dcba46178f69f6cbbea`](https://github.com/mikecarper/MeshCore/commit/ea8176ddc6b2caa7e52f8dcba46178f69f6cbbea) |
| Target / installed profile | `solarxiao_33S_repeater` / Full |
| Version | `v1.18.0.1-halo-keymind-cascade-dev-ea8176dd` |
| Application body hash | `5A46FDAABF34C62D` |
| Application size | 595,040 bytes |
| Application SHA-256 | `d6068baf837c0348ea841a04a2412bd4724a93022f2d8b750af15ca1fb4fbe76` |
| Full / Reduced qualification | PASS: build, runtime memory, DFU, UF2 and linked capabilities |
| Native power marker in both images | PASS |
| Native host test methods | 3 PASS, including eight core scenarios and real Wire/atomic-store boundaries; ASan/UBSan |
| XIAO startup/shutdown checks | 6 PASS, including GPIO safety negative controls |
| Powered USB readings | 75 named register fields; FST chemistry code 6, four cells |
| Settings / persistence | 37 commands including 10 rejected writes; readback, restart and exact register restoration PASS |
| LoRa carrier telemetry | PASS: three replies with all carrier channels 2..13 |
| Repeater forwarding | 3 PASS; exact nonce, four-byte route, one target hop |
| Bootloader | HEAD `b07255d4cdc601f1313e4cbe020caad3b5544821`, CRC `76EBABBF`, preserved |

Full has 150,608 internal bytes available against 76,960 required by the runtime
memory check; Reduced has 152,256 available. The installed public key, primary
radio, RX power saving and bridge settings remained unchanged. Repeating stayed
on and TX stayed -6 dBm. Each trace added one direct RX and TX with zero receive
errors. The cumulative receive-error counter was 2 after the trace run and 17
after all telemetry work; core error flags remained zero. The trace partner's settings were preserved and endpoints closed.

## Powered bench acceptance

The user supplied 13.2 V at SOLAR/VIN with BAT disconnected and USB connected.
Initial native readouts were approximately 13.2926 V input, 13.2785 V output,
27.76 C die and 27.73 C modeled NTC temperature. BAT was open: its changing
floating/capacitor voltage is not a battery measurement or a charger load test.
The charger reported `battery_short` while BAT was disconnected.

The test exercised force/fast telemetry, MPPT, input-current limiting, manual
input-voltage floor, suspend/resume, JEITA selection, manual charge current and
cell voltage, C/x threshold, CV/total timers and saved calibration metadata.
For example, 13000 mV input floor read back as 13078.1 mV, matching the hardware
step. Manual targets of 1000 mA and 3500 mV/cell read back correctly with JEITA
off. These are register-interface tests without a connected battery.

Saved policy reloaded after restart with nine register overrides and the
explicit calibration-source flag. Every modified register was restored to its
captured value, then `mppt reset` cleared saved overrides and calibration flags.
Final MPPT and JEITA were on; force/fast telemetry were off. Host fault tests
also simulated a charger reset, read/write faults, ignored writes, corrupt or
wrong-size storage, failed atomic publication, identity mismatch, masked-bit
preservation, thermal ordering and one-shot/W0C behavior.

## Supply state, radio checks and scope

The first install check found the charger unavailable. It restored the verified
previous firmware with identity/settings intact; the user then confirmed the
bench supply had been off and switched it on. The final firmware installed and
passed powered reading/control tests.

During a later interval when the charger was unavailable again, authenticated
LoRa CLI returned an explicit unavailable status while INA260 readings remained
available. Three telemetry replies carried channel-2 voltage/current/power;
charger channels were omitted. Temporary contacts and forwarding connections
were removed. One remote version read required a retry.

After the supply was switched on again, authenticated LoRa commands identified
FST/four cells and read charger/battery/status values. Three subsequent telemetry
replies contained every carrier channel 2..13: input 13.29 V, output 13.27..13.28 V,
die 25.4..25.5 C and modeled NTC 24.9 C. Two telemetry attempts missed replies before a successful retry. An earlier powered CLI session also needed retries and
missed its first telemetry response; all temporary contacts/forwards were cleaned
up. Final USB checks confirmed VIN 13.2926 V, MPPT/JEITA on, zero saved
overrides, zero calibration flags and the same firmware/bootloader identities.
These results establish successful readout, not a loss-free radio link.

No actual battery charging, loaded-current calibration, resistance measurement
or ship-mode entry was tested. The default 10 milliohm sense resistors and
10 kohm / 3490 K NTC model come from reference documentation; the supplied
Standard schematic uses a single-cell L42M, not this exact 12 V FSTM revision.
Actual carrier component values and the temperature model remain configurable.

The new application was installed by USB DFU. This run does not repeat a full
LoRa firmware transfer; the earlier successful HEAD bootloader/OTA transfer is
in the [separate OTA report](solarxiao_33s_head_bootloader_lora_ota_2026-10-21.md).
Reduced was build-checked, while live tests used Full. An exploratory Room
Server build exceeded its flash/UF2 limits; native power controls are therefore
scoped to the requested SolarXiao repeater targets. No Room Server or Companion
package is qualified by this report.
