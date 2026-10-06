# Get started

You need a [supported repeater](hardware.md) (a RAK3401, or a RAK4631 on a RAK19003 as in the RAK10703 kit, which is an alpha), ideally with a RAK12027 (Omron D7S) sensor fitted, and a computer with a USB cable and a Chromium-based browser (Chrome, Edge or similar).

## 1. Flash the firmware

Open the [Quake Repeater flasher](https://apps.meshamerica.com/quake-repeater/), choose your board (the RAK3401, or the RAK4631 on a RAK19003 from the RAK10703 kit) and follow it. It flashes the latest release over USB, then has a **Configure** step for the settings below. Releases are also listed on [GitHub](https://github.com/Mesh-America/mesh-america-quake-repeater/releases).

<figure>
  <img src="/img/flasher-welcome.png" alt="The Quake Repeater flasher's welcome page, with Start flashing and Configure your repeater buttons" />
  <figcaption>The flasher: choose Start flashing, or Configure your repeater if the firmware is already installed.</figcaption>
</figure>

Updates can also be sent over the air (Bluetooth or LoRa) once a repeater is running the firmware: see [Update over the air](ota-updates.md).

A freshly flashed repeater is named `Quake Repeater` until you rename it. `ver` shows the firmware, for example `Quake Repeater v1.17.1.6`.

## 2. Set the clock

A repeater without a battery-backed clock or GPS loses the time when it loses power. Set it with `time <epoch seconds>` (the flasher's Configure step warns if it looks wrong). From release 1.17.1.5 the firmware also keeps the clock from going backwards across a restart; see [The repeater's clock](clock-floor.md).

## 3. Set the location and the alert channel

Alerts name where the shaking was felt, so the repeater needs to know where it is:

```
set lat 47.61
set lon -122.33
set earthquake.channel #seismic-test
```

Use a **test channel** first, such as `#seismic-test`, and move to your production channel (for example `#seismic`) only after one to two weeks of quiet running (see step 6). Channel names use letters, digits and dashes. `#test`, `#bot` and the Public channel are refused. Nothing is sent until both the channel and the location are set.

## 4. Test it

```
earthquake test
```

posts a message beginning `TEST:` (at most one every 30 seconds). `earthquake status` shows whether the repeater is ready and, if not, what is missing.

Setup in full, including the commands and what happens during an event, is in [Earthquake channel alerts](earthquake-alerts.md). Every command an owner needs is in [How to admin your repeater](admin-guide.md).

## 5. Mount it well

Where and how you mount the repeater is crucial. Fix it to something solid that does not move, keep it out of the reach of wind-driven sway, secure the antenna and cables, and do not mount it anywhere movement is normal (vehicles, boats, trees, tall flexible masts, fences, doors, machinery). The sensor reads the movement of its own enclosure, so anything that moves it looks like shaking. Full guidance is in [Placement, mounting and testing](placement-and-testing.md).

## 6. Run on a test channel first

Leave the repeater on the test channel, in its final position, for **one to two weeks**. If any alert arrives that was not an earthquake, fix the mounting and start the period again. When it has run quietly, switch to the production channel:

```
set earthquake.channel #seismic
```

## 7. Know what an alert tells you

::: warning Before you share the channel
Read [What the sensor readings mean](reading-the-sensor.md) first, so people understand that one alert is a local shaking report and not an earthquake announcement.
:::
