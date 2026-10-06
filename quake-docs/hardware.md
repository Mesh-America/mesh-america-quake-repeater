# Supported hardware

The Quake Repeater firmware runs on two WisBlock builds. Both use an Omron D7S earthquake sensor on a RAK12027 module, and both are flashed from the [web flasher](https://apps.meshamerica.com/quake-repeater/).

| Hardware | Status | Radio |
|---|---|---|
| **RAK3401** (RAK19007 base, RAK4631 core, RAK13302 1 W module) with a RAK12027 | Tested | 1 W |
| **RAK4631 on a RAK19003 base** with a RAK12027: the RAK10703 kit | **Alpha: not yet run on this hardware** | 22 dBm (no external amplifier) |

::: warning The RAK10703 build is an alpha
The firmware for the RAK19003 is built from the same code as the tested RAK3401 firmware, but nobody has run it on this hardware yet. The flasher shows an "untested firmware" warning and asks you to accept it. If you try it, please [tell us what you see](https://github.com/Mesh-America/mesh-america-quake-repeater/issues).
:::

## The RAK10703 earthquake sensor kit

[RAK's WisBlock Earthquake Sensor Solution Kit](https://store.rakwireless.com/products/wisblock-earthquake-sensor-solution-kit-wisblock-rak10703-k-wisblock-rak10703) is a ready-made package for this firmware's second build:

- a **RAK19003** WisBlock mini base board,
- a **RAK4631** core module (nRF52840 and an SX1262 LoRa radio), pre-flashed with RAK's own firmware,
- a **RAK12027** earthquake sensor module (Omron D7S),
- an IP65 Unify enclosure with a solar panel and a mounting plate with an integrated LoRa antenna.

The **RAK10703-K** kit comes as separate modules without a battery; the **RAK10703** solution is assembled and includes one. The firmware does not need the kit: any RAK4631 with a RAK12027 on a WisBlock base that fits both should work, as long as the hardware matches.

Flashing replaces RAK's firmware with this one, so the board becomes a MeshCore repeater with earthquake alerts. Use the flasher's RAK4631 option and follow its steps, including the OTAFIX bootloader notice.

### Where the sensor goes

On the RAK19003 the RAK12027 goes in **slot D**. It is 23 mm long; slot D takes modules that long and slot C only takes 10 mm modules. The sensor is on the board's main I2C bus at address 0x55, and its interrupt pin is not used by the firmware, so nothing else needs wiring.

Unlike the RAK3401, the sensor does not share a signal with the base board's power enable here, so the firmware needs no special handling for it. Details and what is still unverified are in the [D7S integration notes](d7s-integration.md).

### What to expect

- **Range.** The RAK4631's radio transmits at up to 22 dBm, with no amplifier like the RAK3401's 1 W module. Expect a shorter range for the same antenna and site.
- **Everything else is the same.** Alerts, the message format, the commands, the clock handling and over-the-air updates work as on the RAK3401. Start with [Get started](getting-started.md) and the [admin guide](admin-guide.md).
- **Report what you see.** Whether the sensor is detected at boot (`earthquake status` shows its state), what a gentle shake does to its readings, and how far it reaches are all unknown for this build.

## Other hardware

Nothing else is supported. A RAK4631 with a different sensor module, or a different board, would need a firmware build of its own.
