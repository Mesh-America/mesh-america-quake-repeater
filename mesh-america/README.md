# Mesh America provider catalogs

The two active provider catalogs select the 1.17.1.7 USA Cascade release family. Each lists 536 unique qualified firmware profiles across 103 hardware cards; one compatible profile appears under two cards. Both catalogs use the same binaries. The logging catalog remains a separate stable provider URL for existing Mesh America installations.

```text
Provider name: Keymind Cascade
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-v1.16.0-provider.json

Provider name: Keymind Cascade Logging
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-logging-v1.16.0-provider.json
```

The `v1.16.0` part of those filenames is a stable provider URL, not the firmware version. Both JSON files contain exact 1.17.1.7 asset URLs, including the separate Companion, repeater and room server, utility, LoRa OTA, and Full ESP32 release pages.

Four 256 KiB STM32WL USB Companion images (RAK 3x72, Tiny Relay, Wio-E5 Mini, and Wio-E5) omit packet diagnostics to preserve their 32 KiB LittleFS layout. Their USB Companion transport remains available. Their entries say so explicitly. Other logging controls follow each exact image's capability manifest.

See the [1.17.1.7 release guide](../docs/releases/1.17.1.7.md) and [firmware picker](../docs/firmware_picker.md). ESP32 partition migration packages are on the utility release page. nRF52 application images require a matching OTAFIX bootloader when the installed bootloader is not already compatible.

Catalogs are generated from the staged release manifest, with every asset URL checked against the staged file and tag. Historical `provider-backup.json` files are retained unchanged.
