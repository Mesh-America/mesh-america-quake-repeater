# Releasing Firmware

For 1.17.1.9 and later, build the complete qualified local release from a
clean, committed checkout. The builder runs one PlatformIO process at a time:

```bash
python3 scripts/build_local_release.py \
  --firmware-version v1.17.1.9-halo-keymind-cascade-dev --pio-jobs 4 --resume
```

Package its completed directory for stable publication:

```bash
python3 scripts/package_cascade_release.py \
  --input .releases/v1.17.1.9-halo-keymind-cascade-dev-SOURCE8 \
  --output /path/to/publication-stage --local-release --stable \
  --version 1.17.1.9 --commit FULL_SOURCE_COMMIT
```

The packager rechecks the local checksum inventory, qualified firmware,
full/reduced nRF52 pairs, and every exact ESP32 migration package. It keeps
migration-only application identities inside their migration ZIPs. It does
not upload anything. Review `release-plan.json`, generate the picker controls
as described in [the picker guide](docs/firmware_picker.md), and generate
both Mesh America catalogs from the same staged asset manifests:

```bash
python3 scripts/generate_mesh_america_release.py \
  --stage /path/to/publication-stage \
  --catalog mesh-america/keymind-cascade-v1.16.0-provider.json \
  --output /path/to/new-provider.json
```

Both active provider URLs use the same binaries. Preserve their stable
filenames when updating them. Create supporting releases first and publish
the Companion family root last, marking only that root as GitHub Latest.
Upload each group's complete asset inventory and verify the public asset
names, sizes and checksums before switching the catalogs. Regenerate the
downloadable picker from the same family and update its checksum on every
page. Documentation-only follow-up commits do not move firmware tags.

For the USA Cascade 1.17.1.5 matrix, use
[the option 3 release instructions](docs/old-releases/1.17.1.5.md).
Package the qualified outputs with `scripts/package_cascade_release.py`.
Local staging does not publish or push anything. Include the
[feature switches by role](docs/role_feature_switches.md),
[Full Companion guide](docs/full_companion_features.md), and
[USB web console](https://flasher.meshcore.io/console) in each role's notes.
The five 1.17.1.5 pages are development prereleases.

## Legacy tag-triggered GitHub Actions

The repository also has older workflows matching `companion-*`, `repeater-*`,
and `room-server-*` tags (for example `repeater-v1.0.0`). They invoke the shared
`firmware-builder.yml`, build their own target set, and request a draft release.
They are separate from the qualified option 3 matrix and local release staging.

The older broad `repeater-*` trigger also matched `repeater-room-*` Cascade tags.
For 1.17.1.5 that workflow added its own artifacts and changed the title of the
already-published Repeater/Room Server page. Do not assume a published Cascade
page is untouched while that workflow is running. Check workflow completion,
release title/body, and the final asset inventory after publication. Preserve
existing assets when making a documentation-only release edit.
The current trigger explicitly excludes `repeater-room-*`.

Use role-specific introductions for Companion, Repeater/Room Server, Sensor,
LoRa OTA Repeater, and expanded Full infrastructure pages. Link the exact
board/storage [OTAFIX 2.4.6 release](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/releases/tag/0.11.0-OTAFIX2.4.6)
where nRF52 bootloader requirements apply. Later documentation commits can be
linked from release notes without moving the firmware tag or rebuilding assets.
