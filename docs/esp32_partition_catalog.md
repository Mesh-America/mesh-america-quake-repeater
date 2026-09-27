# ESP32 release partition lookup table

The canonical LUT is `firmware/esp32_partition_catalog.json` in this fork.
`scripts/precompute_esp32_partitions.py` regenerates it from GitHub release
assets. MeshCore Open bundles an identical copy for offline phone updates.
There is no need to run a command on the phone or download old firmware there.

## Coverage

The initial snapshot enumerates every published release (including prereleases,
excluding drafts) in these repositories, without a recent-release cutoff:

| Repository | Releases | Inspected ESP32 factory images |
| --- | ---: | ---: |
| meshcore-dev/MeshCore | 94 | 1,998 |
| IoTThinks/EasySkyMesh (PowerSaving) | 14 | 336 |
| mikecarper/MeshCore (including keymindCascade releases) | 69 | 7,808 |

All 10,142 standalone `-merged.bin` / `-cleanInstall.bin` images were parsed,
with nine distinct partition tables and no unresolved selected assets.
PowerSaving release tags can contain several firmware patch versions; the LUT
uses each asset's version, not merely its containing release tag.

Eleven releases have no standalone ESP32 factory image. These include nRF52
update chains, RP2040/nRF52-only releases, an empty release, checksum-only
metadata, and the ZIP-only Station G3 KISS modem package. They remain in the
release inventory with an explicit note, but supply no inferred ESP32 layout.
Unpublished builds, custom partition tables, and partition tables inside ZIP
archives are not covered. This is an inventory of published factory layouts,
not a claim that every Git revision has a known layout.

## Matching and safety

1. Ask the device for `get storage.layout` internally. Complete, valid OTA slot
   measurements take precedence over the LUT. A truncated reply is not proof
   that a slot is absent.
2. Otherwise match board, role, and complete firmware version. Prefer the exact
   build hash when reported and present. Preserve profile candidates; do not
   conflate PowerSaving, upstream, and fork version suffixes or V4/R8 boards.
3. Compare the chosen application length against both OTA slots (use the
   smaller slot so the next update also fits). If multiple profiles disagree,
   only make a fit/expansion recommendation when all candidates agree.
4. An oversized image needs a supported exact-board two-stage migration bundle.
   A single-app layout cannot accept the bridge via normal dual-slot OTA and
   needs cable installation. Unknown layouts remain explicitly unknown.

Version-based results are **estimates**. OTA usually replaces only the app, so
a newer version can run on an older partition table. Never use this LUT alone
to authorize a partition-table write. The migration bridge must validate the
actual flash geometry and identity recovery on the device before the final
application upload. See [two-stage migration](esp32_wifi_partition_migration.md).

The phone blocks known oversized regular uploads and opens its two-step
migration section. Companion updates use the same capacity guard, but the
Companion screen does not yet perform partition migration; it offers a smaller
exact-board image or cable migration when necessary.

## Schema 1

- `repositories`, `generatedAt`: snapshot provenance.
- `releases`: repository, tag, publication date, asset counts and coverage note.
- `builds`: release index, original asset name/ID/size/GitHub digest, board,
  role/profile, version, full build version and layout key.
- `layouts`: table SHA-256 mapped to partition entries, minimum OTA slot size
  and `dualOta`. Entry fields are `[type, subtype, offset, size, label, flags]`.
- `unresolved`: selected assets that could not be read or parsed, with reasons.

The generator reads at most the first 36 KiB of each image, including partition
tables at merged-file offset 0x8000 or 0x7000. It validates partition bounds,
overlaps, duplicate app subtypes and the table MD5 when supplied. GitHub asset
digests are recorded as provenance; a prefix read does **not** verify the full
asset SHA-256. This LUT is not a substitute for firmware download verification.

## Refresh and tests

Use an authenticated `gh` CLI and Python 3. The generator has bounded downloads,
retries, and a disposable prefix cache keyed by asset identity/update metadata.
No secrets or firmware binaries are committed.

```sh
python3 scripts/precompute_esp32_partitions.py \
  --output firmware/esp32_partition_catalog.json \
  --cache-dir /tmp/meshcore-partition-catalog-cache \
  --copy-to ../meshcore-open-android-5.1.1/assets/firmware/esp32_partition_catalog.json
python3 test/test_partition_catalog.py
```

`--cached-inventory` deliberately reuses the saved release listing for a
resumable, reproducible snapshot. Omit it to discover newly published assets.
Review coverage counts and `unresolved` after each refresh before shipping the
LUT. No scheduled refresh job or release upload is installed by this script.
