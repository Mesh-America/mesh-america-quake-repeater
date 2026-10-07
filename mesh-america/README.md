# Mesh America provider catalogs

The two active provider catalogs select the 1.17.1.9 USA Cascade release family. Each lists 463 unique qualified firmware profiles across 103 hardware cards (464 firmware entries). Both catalogs use the same binaries. The logging catalog remains a separate stable provider URL for existing Mesh America installations.

```text
Provider name: Keymind Cascade
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-v1.16.0-provider.json

Provider name: Keymind Cascade Logging
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-logging-v1.16.0-provider.json
```

The `v1.16.0` part of those filenames is a stable provider URL, not the firmware version. Both JSON files contain exact 1.17.1.9 asset URLs, including the exact release page for each qualified Companion, infrastructure, sensor, and terminal profile.

Four 256 KiB STM32WL USB Companion images (RAK 3x72, Tiny Relay, Wio-E5 Mini, and Wio-E5) omit packet diagnostics to preserve their 32 KiB LittleFS layout. Their USB Companion transport remains available. Their entries say so explicitly. Other logging controls follow each exact image's capability manifest.

See the [1.17.1.9 release guide](../docs/releases/1.17.1.9.md) and [firmware picker](../docs/firmware_picker.md). An ESP32 `flash-wipe` merged image installs the bootloader, partition table, and application over USB. An app-only `flash-update` image requires an already compatible layout; it cannot expand partitions. If the installed firmware supports it, run `get storage.layout` to inspect the live partition table; firmware version alone cannot confirm the layout. For an existing node that must retain a Wi-Fi or LoRa update path, check the [utility release](https://github.com/mikecarper/MeshCore/releases/tag/utility-v1.17.1.9-halo-keymind-cascade-dev-88c85108) for its exact board and role migration ZIP and follow the README inside. Back up identity and settings, and plan for cable recovery if power fails during the partition-table write. nRF52 application images require a matching OTAFIX bootloader when the installed bootloader is not already compatible.

Catalogs are generated from the staged release manifest, with every asset URL checked against the staged file and tag. Historical `provider-backup.json` files are retained unchanged.
