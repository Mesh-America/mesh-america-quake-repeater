# Update over the air (OTA)

Once a repeater is installed on a roof or a ridge, you can update it without a cable. Download the firmware files from the [flasher](https://apps.meshamerica.com/quake-repeater/) (its "download firmware for OTA updates" link) or from the [GitHub releases](https://github.com/Mesh-America/mesh-america-quake-repeater/releases), then use either method below.

## First, the OTAFIX bootloader

Updating over the air needs the OTAFIX bootloader on the board. If you have not installed it, do that once, **over USB**, by copying the bootloader file onto the board when it shows up as a drive.

::: danger Install a bootloader over USB only
Sending a bootloader through a Bluetooth DFU app has made a radio unresponsive (it needed a long reset hold and a reflash). Keep power and the USB cable connected until it finishes.
:::

## Bluetooth OTA

On the repeater's console run `start ota`, then send the firmware package (`.zip`) to the board with a Bluetooth DFU app, for example nRF Connect or Nordic's nRF Device Firmware Update.

## LoRa OTA (over the radio)

A LoRa update is built on a computer from the new firmware image (`.hex`) and, for a delta, from the `.hex` of the version the repeater runs now, so keep the `.hex` of each version you install. The firmware project's [LoRa OTA guide](https://github.com/Mesh-America/mesh-america-quake-repeater/blob/main/docs/ota_easy.md) has the steps.

## Going back to an earlier version

If the newest firmware gives you trouble, you can install an earlier one. In the [flasher](https://apps.meshamerica.com/quake-repeater/), choose your board and, in the **Confirm** step, pick the version from the **Firmware version** list. The flasher offers only earlier releases it has checked, shows a note that you chose an older version, and links to that version's release notes. For an update over the air, download the earlier release's package from the [GitHub releases](https://github.com/Mesh-America/mesh-america-quake-repeater/releases) and send it the same way.

Flashing an earlier version keeps the repeater's saved settings (name, location, channel and the rest), including when you go back from 1.18 to 1.17. An older version may lack newer features. For example, firmware before 1.18.0.1 does not read the RAK1906 environment sensor, and the oldest versions do not restore the clock after a restart (see below). One known problem: on the RAK4631 image, version 1.18.0.1 leaves the earthquake sensor and the RAK1906 out of the telemetry (the sensor slots lose power). Update to 1.18.0.2 or later. If you cannot yet, send `set peripherals.mode shared` as an admin and then `reboot`; that keeps the sensors powered. The RAK3401 image is not affected. If you go back because of a problem, please [tell us](https://github.com/Mesh-America/mesh-america-quake-repeater/issues) which version and what happened.

## After an update

A repeater without a clock module or GPS falls back to its built-in date after an update. From firmware 1.17.1.5 it restores its saved time, but check it with `clock` and set it with `time <epoch seconds>` if it looks wrong. See [The repeater's clock](clock-floor.md).
