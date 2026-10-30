<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/solarxiao_ina260_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# SolarXiao INA260 battery telemetry, 2026-10-21

The SolarXaio MPPT 12V LiFePO4 carrier on the Mercerwood bench now reports its
INA260 measurements in the normal MeshCore Full repeater build. With the user
reporting a 13.2 V bench supply applied to BAT, all three LoRa telemetry replies
reported **13.26 V**, with signed current readings of **-11, -8 and -8 mA**.
Three subsequent nonce-bound repeater trace tests passed at **-6 dBm**.

[Machine-readable results](solarxiao_ina260_2026-10-21.safe.json) contain the
measurements, exact firmware identity, trace evidence, cleanup and limitations.

## Discovery and correction

The original Full build contained the INA260 driver, but its carrier I2C pins
were reversed and its generic INA260 address was `0x41`. Read-only diagnostic
transactions identified this board's INA260 at **0x40**, manufacturer ID
`5449`, device ID `2270`, with **SDA=P0.09 (variant pin 30)** and
**SCL=P0.10 (variant pin 31)**. Three USB-only readings were about 0.11125 V
before the user connected the BAT supply.

The SolarXiao target now supplies these carrier pins through `PIN_BOARD_SDA`
and `PIN_BOARD_SCL`, and overrides `TELEM_INA260_ADDRESS` to `0x40`. Generic
XIAO wiring and the generic INA260 address remain unchanged. Discovery tries
the INA260's device-ID check before the INA219 driver can claim the same
address and write an incompatible configuration.

## Qualified build and live acceptance

| Item | Result |
| --- | --- |
| Source revision | [`a947f936ecd279b7b3c97b4d832c4efc9a8a696b`](https://github.com/mikecarper/MeshCore/commit/a947f936ecd279b7b3c97b4d832c4efc9a8a696b) |
| Environment and installed profile | `solarxiao_33S_repeater`, Full |
| Application version | `v1.18.0.1-halo-keymind-cascade-dev-a947f936` |
| Application body hash | `E6E4E0E7CA5DB232` |
| Application image | 579,792 bytes |
| Application SHA-256 | `0ba24397e11c0c30b0e3213ea597c536c4bc075c25fae44fc39fa43ce0e5626b` |
| Full and Reduced builds | PASS; memory, DFU and nine capability markers per package |
| Board startup tests | Six PASS, including carrier pin override and GPIO safety negative controls; ASan/UBSan |
| Warm restart | PASS; sensor discovery, identity and saved settings preserved |
| LoRa telemetry | Three replies; channel 2 has voltage, current and power |
| Repeater traces | Three PASS; exact nonce, four-byte route and one target hop |
| Trace direct RX/TX | 1 / 1 per round; zero added receive errors |
| Final core error flags | Zero |

The requested setup retained USB power, applied the supply to BAT and left
solar disconnected. This checks sensor discovery and functional readout;
it does not calibrate the INA260 against an independent voltage reference.
Channel 1 is the XIAO internal ADC reading. Channel 2 is the carrier INA260.
Reported power was 0 W in these near-zero signed-current samples; it is not
an independent power or charger-performance measurement.

The normal radio remained `910.5250244,62.5,7,5`, repeating stayed `on`, and
TX stayed `-6` dBm. RX power saving remained
`on,level=8,preamble=16,rx=39657,sleep=15975`. The telemetry controller's
temporary contact and forwarding connection were removed, the trace partner's
settings were preserved, and USB endpoints were closed.

## Scope and retained evidence

The installed application was updated through USB serial DFU. The qualified
HEAD bootloader remained at revision `b07255d4cdc601f1313e4cbe020caad3b5544821`,
manifest CRC `76EBABBF`. The earlier full LoRa OTA transfer on application
`efad0076` is documented in the
[bootloader and LoRa OTA report](solarxiao_33s_head_bootloader_lora_ota_2026-10-21.md).
This run verifies LoRa telemetry and repeater forwarding on `a947f936`; it
does not repeat a complete firmware transfer on that application.

An additional UART-pin diagnostic probe timed out after the successful INA260
reads. The original application and settings were restored before installing
the final fix. The first trace run passed all three RF traces but failed a
cleanup assertion that compared the entire changing `radio2.status` response.
The corrected check compares saved radio settings exactly and verifies radio2
remains off; the subsequent complete run passed. Its final cumulative receive
error counter was 7, with zero added during each owned trace round.

No LTC4162 charger configuration registers were written. The charger SKU is
LTC4162-FSTM as reported by the user. Charging behavior and other carrier
revisions are outside this acceptance result. The Reduced package was
build-checked only; live INA260 acceptance used the Full package.
