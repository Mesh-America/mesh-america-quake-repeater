<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/research/esp32_full_build_audit_2026-10-06/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Why ESP32 builds still have options besides Full

Audit date: 2026-10-06. Source baseline: `2ee62b981435df7dc4bcd79de39e61a4d5e98652` on `keymindCascade`.

## Implemented consolidation

After the audit, the ordinary ESP32 release policy was changed to publish Full
only. The exact selector replay goes from **317 planned images to 172**,
removing all 145 standard/reduced slots. All 172 previous Full target
identities, compiled PlatformIO environments, and Full overlay flags remain
identical; no new Full compilation recipe or capacity requirement is introduced.
The baseline findings below describe the policy before this change.

The ordinary board/role resolvers omit ESP32 reduced aliases. Every selected
infrastructure Full image is built once, using its existing exact recipe and
identity. Generated Full Companion keeps its registered USB/BLE/WiFi source
environment. Resume packaging removes stale standard, minimal, transport,
runtime-setting, and development artifacts instead of reintroducing them.
Unverified ordinary Full images fail qualification. Other chip families keep
their existing profile policies, and KISS remains a distinct host-modem role.

The measured T-LoRa UART/MQTT transport split and capacities within Full are
preserved. Direct explicit recovery recipes and reviewed partition-migration
packages remain available separately. The existing same-partition identity
allowlist is deliberately retained for OTA compatibility checks; broadening
release selection does not authorize an app-only update across layouts.

Not every board has a reviewed wireless expansion package. Targets outside
the migration catalog require USB/serial for a partition-table change. The
[updated migration guide](../esp32_wifi_partition_migration.md) explains this
distinction and the supported cable-free routes.

The [complete baseline inventory](esp32_full_build_inventory_baseline_2026-10-06.csv)
contains all 636 primary logical names and four optional local HIL names,
including their exact Full mappings. The [post-change selector comparison](esp32_full_release_selection_2026-10-06.json)
records zero standard/reduced slots, zero duplicate identities, and no change
to any previous Full source recipe.

## Decision being audited

Prefer one Full image for each exact board and firmware role. A smaller image
needs a demonstrated RAM limit or a demonstrated failure to fit the largest
safe application layout for that board and role. An image failing an old,
small OTA slot does not establish either condition.

This audit examines the resolved PlatformIO recipes and the release builder's
generated aliases and routing. It distinguishes options a user can explicitly
build from artifacts that the normal release matrix actually publishes.
Existing measurements are identified by their original revision; they are not
presented as fresh builds of the audit baseline. This is a source and evidence
audit followed by release-policy consolidation and focused validation, not a
rebuild or hardware qualification of every ESP32 target.

## What Full means

Full is a feature profile within a firmware role. A Full Companion combines
the board's qualified app transports and text terminal. A Full Repeater,
Room Server, or Sensor keeps the supported infrastructure features, logging,
and OTA support. These roles have different jobs and remain separate images.
Different radios, pin maps, displays, and expansion hardware also remain
separate exact board recipes.

Full does not mean every board has identical contact counts, queue lengths,
or routing-table capacities. Reducing a table to meet a measured RAM budget
can preserve the Full feature set. Nor does a compiled feature have to run all
the time: runtime settings can turn off WiFi, logging, or other supported
services without installing a different image.

There are two implementations with confusingly similar names. Named
`*_companion_radio_full` targets are Full Companion even when the infrastructure
`ESP32_FULL_BUILD` overlay is not set. Counting only that overlay would
incorrectly call these images non-Full.

## Why the other options exist

### Genuine RAM constraints

The T-LoRa V2.1-1.6 combined UART, MQTT, and ESP-NOW image has a retained
linked measurement of 190,488 available internal bytes against 196,984 required
bytes: a 6,496-byte shortfall. It therefore retains separate UART/ESP-NOW and
MQTT/ESP-NOW Full images. This is evidence for a transport-combination
exception, not for dropping Full on the entire board. See
[the firmware RAM policy](firmware_memory_budget.md).

Other constrained boards already run Full with board-specific capacities.
The [2026-10-02 Companion audit](../test-results/heltec_v3_preview3_ram.md)
records passing ordinary Full builds for Heltec V2/V3, Wireless Tracker,
Tracker V2, CT62, XIAO C3, Generic ESP-NOW, T-Beam, and T-LoRa. Some margins
are small: Generic ESP-NOW had 1,536 bytes and Tracker V2 had 2,254 bytes
above the unchanged linked runtime allowance. A pass establishes that exact
image's budget, not sustained runtime or room for future feature growth.

PSRAM does not eliminate all RAM limits. Bluetooth, WiFi, DMA buffers, and
some allocations still require internal RAM. The guards exclude PSRAM from
the internal budget; classic ESP32 additionally has a static DRAM-placement
limit. See [the classic ESP32 budget](esp32_memory_budget.md).

### Older installed partitions and update identities

Portable standard and `*_lora_ota_no_external_sensors` images can fit a
historical 1.25 MiB OTA slot. On qualified targets, Full fits after expansion, but
ordinary app-only OTA cannot rewrite its partition table. LoRa OTA also
checks the exact target identity and layout; merely renaming a Full image
does not make it a valid update for an old installation.

This explains recovery and migration artifacts. It does **not** establish a
hardware capacity exception. Once a supported device has migrated, its
ordinary role image should be Full. A small migration bridge remains useful
as a tool, rather than as a second everyday firmware choice. The
[migration guide](../esp32_wifi_partition_migration.md) describes the supported
layouts, preservation checks, and current limitations of cable-free migration.

### Legacy transport and settings recipes

Many USB-only, BLE-only, WiFi-only, Terminal Chat, power-saving, and FEM-default
recipes still exist so an exact old name can be built. Where an exact Full
replacement exists, the normal release matrix already suppresses many of
these duplicates. Their presence in PlatformIO is not proof that they must
appear in the firmware picker or that Full cannot fit.

The release builder also retains explicit `--standard` and explicit reduced
OTA requests. These selectors intentionally override automatic Full selection.
That is a compatibility/developer policy, not a measured RAM or maximum-flash
finding.

### Different roles and development tools

KISS modem firmware exposes a raw modem protocol; it is not the Companion
application protocol or a MeshCore Repeater. Its existence is a role decision,
not an argument that the board cannot support Full. Partition migrators,
expanders, legacy-layout seeds, and simulation fixtures likewise have a
specific test or installation job. The normal release matrix excludes those
development tools. They should be considered separately from everyday
non-Full node images.

### Eligibility rules and missing qualification

The infrastructure Full selector uses recipe metadata, including admin,
MQTT, and ESP-NOW markers. Companion Full qualification also needs an exact
combined recipe or a qualified replacement. These rules can exclude an
option without measuring its RAM or largest safe flash layout.

An absent Full recipe, an eligibility-list omission, or an old compile failure
is an **unproven exception**. It requires qualification or an explicit product
decision; it must not be described as a demonstrated capacity failure.

## What counts as the maximum partition

Flash is divided among boot metadata, applications, and persistent data.
Infrastructure self-update requires two application slots; it cannot use
the entire chip as one app slot. Companion Full can be a host-backed LoRa
OTA sender without being a LoRa self-update destination, so some Companion
layouts intentionally use one larger application slot and require USB for
self-updates.

T-Beam 1W Full Companion keeps LilyGo's factory-compatible single 3 MiB app
slot even though the board has 16 MiB flash. This is a boot/layout and
source-role contract, rather than a failure of Full to fit its physical flash.

| Physical flash | Normal expanded infrastructure slot | Upper dual-slot ceiling with only 64 KiB data storage |
| --- | ---: | ---: |
| 4 MiB | 2,031,616 B (`0x1F0000`) | 2,031,616 B (`0x1F0000`) |
| 8 MiB | 3,342,336 B (`0x330000`) | 4,128,768 B (`0x3F0000`) |
| 16 MiB | 6,553,600 B (`0x640000`) | 8,323,072 B (`0x7F0000`) |

The upper ceilings assume 64 KiB before the first application, equal
64 KiB-aligned application slots, and 64 KiB of filesystem storage, with no
additional coredump or mandatory data region. They are arithmetic bounds,
not qualified partition plans. Required data, preserved offsets, or a larger
minimum filesystem can lower the safe bound. The existing 8/16 MiB layouts
retain substantially more storage and a coredump partition; their current
slot sizes are therefore not the absolute physical maximum.

SenseCAP Indicator's 8 MiB preserved-data Full layout is a further exception:
it keeps 2,621,440-byte (`0x280000`) OTA slots and the old filesystem/coredump
addresses. Its first slot ends at the preserved filesystem boundary, so both
usable OTA slots have that limit despite the larger chip. This is a data-layout
constraint; it must be distinguished from an absolute flash-capacity limit.

A Full size failure against the legacy 1.25 MiB ceiling, or against an
existing 8/16 MiB default slot alone, is insufficient evidence for a permanent
minimal image. The audit must first establish the board's actual flash size,
the role's update requirements, and its minimum safe persistent-data layout.

## Baseline audit inventory and outstanding qualification

The primary repository configuration contains **500 concrete ESP32
environments and 136 builder-generated aliases: 636 logical target names**.
They are recipes and identities, not 636 separate everyday images. The
canonical resolver keeps 374 names, including 43 KISS modems; the default
non-KISS node selection contains 331 names.

Evaluating the real release-matrix selectors and the per-build Full promotion
rules gives **317 planned ESP32 node artifact slots: 172 Full and 145
non-Full**. These are pre-build selections, not an assertion that 317 current
binaries were produced. Size-driven fallback, failed qualification, and the
final package's capability-based consolidation can change the final output.

| Planned non-Full group | Count | Why selected | Finding under the requested capacity-only exception rule |
| --- | ---: | --- | --- |
| `*_lora_ota_no_external_sensors` | 99 | Generated reduced OTA identity explicitly selects standard | Compatibility/profile policy; no per-target RAM or maximum-layout failure is required before selecting it |
| Legacy images in the partition-migration inventory | 24 | Builder deliberately retains portable output during transition to expanded Full | Old installed-layout compatibility, rather than maximum hardware capacity |
| Other complete standard images with a supported Full route | 22 | Their names are outside the curated Full-only and migration promotion lists | Missing policy promotion/partition qualification; not demonstrated capacity exclusions |

**Every primary canonical node target has a supported Full route**, after
mapping a reduced identity to its feature-rich base. That establishes routing,
not that every current Full image has passed a fresh RAM/flash build or
hardware validation. No retained current-baseline failure establishes that
all 145 non-Full selections are necessary because Full cannot fit RAM or the
largest safe partition.

The 22 complete standard choices outside the migration list are:

- Generic ESP-NOW: Repeater and Room Server.
- GEPRC Linkflow 900: Repeater.
- T-Beam SX1262 and SX1276: Repeater and Room Server for each radio.
- LilyGo T-LoRa C6 and T-LoRa V2.1-1.6: Repeater and Room Server for each board.
- M5Stack Unit C6L: Repeater and Room Server.
- Meshadventurer SX1262 and SX1268: Repeater and Room Server for each radio.
- Station G3 ESP32 revision 2: Repeater and Room Server.
- XIAO C6, Meshimi, and WHY2025 Badge: Repeater.

These are candidates for exact Full/layout qualification, rather than an
approved instruction to relabel their old binaries. The T-LoRa transport
combination exception above still applies.

All **52 canonical ESP32 Companion selections are already named Full**;
there are zero canonical non-Full Companions. All 21 standalone ESP32
Terminal Chat names map to exact Full Companion replacements. Most surviving
old transport recipes are therefore direct-build compatibility choices rather
than current release duplication.

This PC's ignored local configuration additionally loads four ESP32 radio
bench fixtures. Three are excluded by the utility-name filter. The fourth,
`profile_four_tx_v4_rx`, escapes that filter and adds one standard selection
when the bench configuration is loaded. It is a local release-leakage risk,
not a clean primary-configuration node option; it is excluded from the counts
above and listed separately in the inventory.

The [capacity evidence snapshot](esp32_full_build_capacity_evidence_2026-10-06.json)
retains 38 historical linked reports for 14 ESP32 target identities, together
with original failures, repairs, app sizes, and partition tables. All 38
reports pass their recorded budgets. Every bound artifact still present in
this checkout matches its saved hash; eight referenced files are absent, so
their saved reports cannot be fully rebound here. These results are historical
evidence, not complete current-source qualification.

### Method and policy locations

PlatformIO resolved the configuration once. The builder was then sourced with
that cached configuration and a failing `pio` stub; the audit evaluated its
actual selectors and intercepted build calls without compiling or flashing.
The local configuration only adds HIL include files, so those 11 optional
environments (four ESP32) were removed from the cached primary inventory
without changing ordinary resolved options. A second selector replay confirmed
the primary counts. Independent policy and memory reviews checked the results.

Relevant source locations at the audited baseline are:

- `build_legacy.sh:245`: environment metadata and generated identities.
- `build_legacy.sh:3244`: infrastructure Full eligibility.
- `build_legacy.sh:3263`: curated Full-only bulk promotion list.
- `build_legacy.sh:3312`: partition-migration legacy/Full list (25 identities;
  24 contribute standard slots in this matrix).
- `build_legacy.sh:4901`: actual per-build profile promotion.
- `build_legacy.sh:5306`, `5400`, and `5595`: exact Companion/Terminal Chat
  replacement and redundant-artifact filtering.
- `build_legacy.sh:6626`: separate Full migration pass.
- `build_legacy.sh:6980`: reduced auto fallback follows selected-slot size
  overflow; it does not prove a maximum-layout failure.
- `scripts/build_local_release.py:105`: final Full/capability consolidation;
  standard records otherwise pass through.
- `scripts/build_local_release.py:407`: normal release explicitly skips KISS.
- `scripts/esp32_full_partition.py`: expanded, preserved-data, and single-slot
  Full partition choices.

The audit itself did not flash a device. The resulting consolidation changes
ordinary release routing and resume selection; existing firmware recipes and
capacity guards are retained.

## Fresh validation of the consolidation

| Exact Full target | Final app size / slot | Linked internal available / required | Result |
| --- | ---: | ---: | --- |
| `LilyGo_Tlora_C6_repeater_` | 2,010,024 / 2,031,616 B | 283,088 / 139,200 B | Passed; 21,592 B flash margin |
| `Heltec_v2_companion_radio_full` | 2,275,368 / 3,342,336 B | 184,680 / 173,840 B | Passed; 10,840 B linked RAM margin |

These sequential embedded builds use the audit baseline plus the release-rule
changes, version `v1.17.1.9-halo-keymind-cascade-dev-fullaudit`. The C6 uses
its supported expanded 4 MiB dual-OTA layout. The generated V2 Full Companion
correctly compiles `Heltec_v2_companion_radio_wifi`; its named Full identity is
preserved. Both produced verified capability manifests and firmware-bound RAM
reports. No physical flashing or runtime qualification is claimed.

Focused release/profile regressions cover the real matrix scheduler, exact
Companion recipe mapping, stale-artifact selection, preserved T-LoRa transport
split, direct recovery access, and unchanged non-ESP32 choices. The complete
`test/test_build_profiles.sh` suite passed, as did 69 Python tests covering
selection, partitions, RAM, and packaging. The 58 selection/partition/RAM cases
ran on native Linux; the 11 packaging cases ran on Windows Python 3.13 because
Linux Python 3.10 lacks the packaging code's pre-existing `hashlib.file_digest`
API. The [selector evidence](esp32_full_release_selection_2026-10-06.json)
records these results and the fresh builds' bound artifact hashes.

## Recommended release rule

Use Full as the everyday choice per exact board and role wherever it passes
the existing RAM guards and the largest safe, supported partition layout.
Retain capacity-tuned Full recipes when they preserve the board's features.
Keep genuinely incompatible transport combinations separate, with their
measured reason documented. Present migration/recovery tools separately from
ordinary firmware and retain old names as compatibility aliases where useful.

Require a passing ELF-bound RAM report and the exact application/partition
sizes for every capacity exception. Do not allow an unexplained name-based
exception to masquerade as a hardware limit. Runtime startup, reconnect,
service-toggle, OTA, and sustained heap checks remain necessary for Full
qualification; build success alone does not cover them.
