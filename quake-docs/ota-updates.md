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

## After an update

A repeater without a clock module or GPS falls back to its built-in date after an update. From firmware 1.17.1.5 it restores its saved time, but check it with `clock` and set it with `time <epoch seconds>` if it looks wrong. See [The repeater's clock](clock-floor.md).
