# Mesh America provider catalogs

Both active provider catalogs now use **1.17.1.5 USA Cascade**, published from
original firmware commit `26303793`, with **52 memory-corrected entries** from
`aa20e927`. All 11 release profiles that failed the RAM budget have replacements;
all 43 nRF52 Full Companions use shared mOTA/queue storage. Wireless Paper Full
now uses source `1e4d1e16`, restoring 350 contacts and 40 channels with 256
message slots normally, or 128 while mOTA borrows the other half. The other six
corrected ESP32 Full profiles use 150 contacts and keep their 256-message queue; read
the entry notes and export contacts before upgrading if you exceed that limit.
The release audit also covers 43 supplemental Full repeater profiles available
on GitHub and in the firmware picker. The catalogs retain their canonical
selection and cover **94 device cards, 540 selectable
entries, 539 unique firmware profiles, and 1,078 unique firmware files**.
One Full Companion image is listed under two compatible device/accessory cards.
The MQTT simulation environment is a laboratory target and is not a device
choice. Entries without a qualified replacement in this OTA-required release
are omitted; no download silently points to an older firmware release.

## Stable provider URLs

The `v1.16.0` text in these filenames is part of the existing provider URL,
not the firmware version. Keep these URLs in Mesh America; they now load
1.17.1.5 choices.

```text
Provider name: Keymind Cascade
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-v1.16.0-provider.json
```

```text
Provider name: Keymind Cascade Logging
Catalog URL:   https://raw.githubusercontent.com/mikecarper/MeshCore/keymindCascade/mesh-america/keymind-cascade-logging-v1.16.0-provider.json
```

## Logging and former variants

Both catalogs now select from the same canonical firmware set. Logging,
power-saving, and controllable gain variants are runtime settings; selecting
the logging provider does not itself change the device's saved settings.
Each entry includes the appropriate commands, update methods, hardware
requirements, and its actual GitHub release page.

- **Full Companion:** ESP32 uses `set usb.logging on` / `set usb.logging off`;
  nRF52 uses `set usb.logging on reboot` / `set usb.logging off reboot` for its
  optional second USB port. MQTT-capable Full Companions use WebConfig broker
  cards, not infrastructure MQTT commands.
- **Infrastructure:** `set usb.logging on` / `set usb.logging off` controls live
  USB logs. MQTT-capable unified Full images use `set logging.output off`,
  `usb`, `wifi`, or `both`; `set bridge.enabled on` / `off` toggles the bridge.
- Open the [USB web console](https://flasher.meshcore.io/console) at 115200 baud.
  Full Companion and infrastructure start in ASCII mode. Download-only board
  entries retain their external programming requirements.

See [feature switches by role](../docs/role_feature_switches.md), the
[release guide](../docs/releases/1.17.1.5.md), and the
[old-variant map](../docs/releases/1.17.1.5-variant-map.tsv).
For nRF52 OTAFIX installations use the exact board/storage profile from
[OTAFIX 2.4.6](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/0.11.0-OTAFIX2.4.6).

## Catalog maintenance

The 1.17.1.5 catalog download URLs were reconciled with `release-plan.json`
and each group's qualified `TARGET-MANIFEST.json`, then verified against the
published GitHub assets. Preserve the exact tag for each file: Companion,
Repeater/Room Server, Sensor, LoRa OTA, and expanded Full profiles are on
separate release pages. Do not update these catalogs by replacing version
strings alone.

The older `update-provider-release.py`, `update-logging-provider-release.py`,
and PowerShell generator target earlier flat release directories and tag
layouts. Their default routing is not sufficient for the five-page 1.17.1.5
staging layout. Before using them for another release, reconcile canonical
aliases, omitted targets, runtime feature descriptions, and release-group
routing against that release's manifests.

Files ending in `provider-backup.json` are historical backups and intentionally
retain their original versions. They are not the active provider URLs above.
