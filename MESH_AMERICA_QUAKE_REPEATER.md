# Mesh America Quake Repeater

Firmware for LoRa mesh repeaters that carry an Omron D7S earthquake sensor (RAK12027), built by Mesh America. It is a fork of [Keymind Cascade](https://github.com/mikecarper/MeshCore) (branch `keymindCascade`), itself a MeshCore variant. This repository builds and releases only Mesh America firmware; its images are isolated from Keymind's and from stock MeshCore.

## What is different

- Runtime-detected D7S sensor support (driver, Wire adapter, telemetry channels, board hook): see [docs/d7s-integration.md](docs/d7s-integration.md) and [docs/d7s-measurement-contract.md](docs/d7s-measurement-contract.md).
- Earthquake channel alerts: one short canned message to a user-chosen hashtag channel when the sensor reports strong shaking, only once a channel and the repeater's location are set. See [docs/earthquake-alerts.md](docs/earthquake-alerts.md).
- A product environment, `MeshAmerica_Quake_Repeater_RAK3401`, in [variants/meshamerica_quake/platformio.ini](variants/meshamerica_quake/platformio.ini). It is a lean, LoRa-OTA-capable RAK3401 repeater. Its environment name gives it its own OTA target id, so it cannot be mistaken for a Keymind image.
- Everything else is Keymind Cascade, unmodified except for the small edits listed in the integration doc.

## Building and testing

```sh
pio run -e MeshAmerica_Quake_Repeater_RAK3401      # firmware (one PlatformIO process at a time, see AGENTS.md)
pio test -e native -f test_d7s                      # driver tests
pio test -e native -f test_d7s_wire                 # Wire adapter tests
pio test -e native -f test_seismic_alert            # alert policy and message tests
```

## Keeping up with Keymind

`keymind` is a read-only remote (its push URL is disabled). To take updates:

```sh
git fetch keymind keymindCascade
git merge keymind/keymindCascade        # conflicts should be limited to the files named in docs/d7s-integration.md
```

## Rules

- Keep Keymind merges easy: new behaviour goes in new files (`D7S*`, `SeismicAlert*`, `MyMeshQuake.cpp`, `variants/meshamerica_quake/`). Edits to Keymind-owned files are small, guarded by `ENV_INCLUDE_D7S`, added at the end of a block or class rather than mid-function, and listed in the "Files relative to Keymind Cascade" section of [docs/d7s-integration.md](docs/d7s-integration.md).
- Do not push to `keymind`. Push only to `origin` (Mesh-America/mesh-america-quake-repeater).
- Commit metadata is public once pushed. Use the configured identity (`Mesh America`, a noreply address); do not put personal email addresses in commits, files or release notes.
- One PlatformIO process at a time in a checkout (Keymind's `AGENTS.md`).
- MIT licensed, with the upstream copyright notices retained (`license.txt`).

## Open hardware questions

See the end of the "Hardware notes" section of the integration doc: the shared IO2 pin (3V3_S enable, booster, INT2) has not been verified under load, and TX power with the sensor fitted has not been measured.
