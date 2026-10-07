<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/research/firmware_choice_followup_2026-10-06/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Further firmware choice consolidation audit - 6 October 2026

Baseline: pulled commit `08bf174ea30e2e075cdd9fc74111580662b461bb`.
The user requested fewer choices after the ESP32 Full-only release change.
This follow-up combines menu/picker changes with a source,
resolved-configuration, and retained-artifact audit. It did not build a matched
nRF52 Full/Reduced pair or run hardware tests. Image-removal candidates below
remain unqualified; the implemented changes simplify selection without changing
firmware sources, partition layouts, or deployed update identities.

## Implemented selection changes

The interactive board menu now uses canonical Full ESP32 targets and omits
transport/default aliases, compact recovery recipes, and development utilities.
On nRF52, normal names and aliases that already build the exact same qualified
Full/Reduced pair appear once. Distinct external-storage and deployed OTA IDs
remain selectable. Exact hidden names remain directly buildable.

| Platform | Supported exact names before | Ordinary menu choices after |
| --- | ---: | ---: |
| ESP32 | 638 | 217 |
| nRF52 | 403 | 209 |
| RP2040 | 25 | 19 |
| STM32 | 16 | 16 |
| Total | 1,082 | 461 |

These are menu targets, including KISS; they are not firmware-file counts. The
current ordinary ESP32 release still has **174 Full node images** (52 Companion,
58 Repeater, 47 Room Server, 17 Sensor). The pull added two Station G3 Sensor
recipes to the previous 172-image plan. No Full image was retired in this
follow-up. The [selector evidence](firmware_choice_followup_selection_2026-10-06.json)
records exact menu/release agreement, zero duplicate menu names, and the
remaining OTA identity constraints.

After selecting an exact board and role, the web picker skips logging,
connection, and profile filters when they do not distinguish firmware builds.
Logging and independent bridge controls remain in the result's setup directions;
linked logging/bridge settings still select their corresponding commands.
A sole install format is inferred; multiple install operations remain explicit.
Real alternatives stay visible even after mutually narrowing filters are selected.
The measured T-LoRa split and nRF52 sensor/storage alternatives remain available.

The complete build-profile suite, 28 ordinary release-selection tests, and two
picker-package tests passed. Picker tests cover skipped requirements, real
alternatives, install formats, existing share links, and runtime command rendering.
The complete form was also exercised in the in-app browser using local replayed
release metadata: a sole app-only Full download, explicit merged versus app-only
installation, nRF52 Full/Reduced UF2 versus ZIP choices, runtime logging changes,
and a partial share link with WiFi logging and ESP-NOW enabled. The correct
files and commands remained selected. This used fixture metadata and did not
download or install firmware, contact a device, or publish the website.

## nRF52 sensor pairs: policy versus demonstrated need

At this baseline, `is_nrf52_sensor_ota_pair_target()` in
[`build_legacy.sh`](https://github.com/mikecarper/MeshCore/blob/08bf174ea30e2e075cdd9fc74111580662b461bb/build_legacy.sh) includes every nRF52 repeater,
room-server, and sensor recipe, including external-QSPI and SD recipes.
`run_nrf52_sensor_ota_pair()` requires Full to pass, then builds Reduced; a
successful Reduced build cannot replace a failed Full build. Thus the pair is
a blanket publication policy, not evidence that each board needs two images.

| Classification | Evidence | Defensible action |
| --- | --- | --- |
| Same declared sensor functionality | The 31 concrete recipes below enable none of the drivers removed by Reduced. GPS is outside the omitted set. | Present Full as the ordinary choice. Treat image deduplication as a candidate until packaged applications are compared. |
| Actual optional-driver difference | Other recipes can enable environmental/ranging drivers; non-RAK recipes can also lose INA monitors. RAK3401/4631 Reduced keeps the four INA drivers and compatible GPS. | Full for normal installs; Reduced can remain an advanced/recovery choice with its missing drivers stated. Disabling a sensor at runtime does not remove its compiled flash cost. |
| Demonstrated internal-OTA headroom constraint | The historical RAK3401 compact chain has several exact transitions with zero staging margin. Current staging capacity depends on the installed image and exact delta, not just the board's nominal flash. | Preserve qualified reduced endpoints and exact-base update routes. This is not proof that every current Full/Reduced pair is necessary. |
| Current measured mandatory pair | No current matched Full/Reduced application and delta-package comparison was found in the retained local evidence. | Do not claim a current pair is required by measured capacity, or claim Reduced can safely be deleted everywhere. |

The baseline [`CLI matrix`](../cli_build_matrix.md) explicitly acknowledges
that boards without optional sensor drivers still receive two named choices,
with small or zero savings. This audit found no qualified artifact pair proving
byte-identical firmware for those boards. The retained RAK3401 1.17.1.8 Reduced
[RAM report](../test-results/preview-1.17.1.8/RAK_3401_repeater_lora_ota_no_external_sensors-ota-v1.17.1.8-halo-keymind-cascade-dev-d5853b9c.memory.json)
passes with 67,660 available bytes versus 66,904 required, a 756-byte margin;
it is historical, not a current matched-pair comparison. The retained T1000-E
reports concern Full Companion, outside this infrastructure pair policy.

Full already includes targeted RAM capacity tuning: T096/T1 repeaters use four
flood rules, and RAK3401 unified uses 47. The baseline script records these as
measured internal-RAM reductions while retaining the Full sensor support.
They justify tuning within Full, not a second sensor profile by themselves.

## 31 concrete recipes with no enabled removable sensor driver

Source: `out/esp32-full-audit-2026-10-06/platformio-current-resolved.json`, the
current resolved configuration retained for the baseline audit. Definitions
and undefinitions were processed in order, and definitions equal to zero were
excluded. The tested omitted set is the 12 environmental/ranging macros in
`apply_lora_ota_no_external_sensors_profile()`, plus four INA macros except on
the RAK recipes which retain them. This is a recipe-level result, not an image
hash result or a count of canonical published outputs.

```text
Heltec_mesh_solar_repeater
Heltec_mesh_solar_room_server
Heltec_tower_v2_repeater
Heltec_tower_v2_room_server
KeepteenLT1_repeater
KeepteenLT1_room_server
LilyGo_T-Echo_Card_repeater
LilyGo_T-Echo_Card_room_server
LilyGo_T-Echo-Lite_repeater
LilyGo_T-Echo-Lite_room_server
MeshTracker_X1_repeater
MeshTracker_X1_room_server
Mesh_pocket_repeater
Mesh_pocket_room_server
muzi_base_duo_repeater
muzi_base_duo_room_server
muzi_base_uno_repeater
muzi_base_uno_room_server
Nano_G2_Ultra_repeater
Nano_G2_Ultra_room_server
t1000e_repeater
t1000e_room_server
t1000e_sensor
ThinkNode_M1_repeater
ThinkNode_M1_room_server
ThinkNode_M3_repeater
ThinkNode_M3_room_server
ThinkNode_M4_repeater
ThinkNode_M4_room_server
ThinkNode_M8_repeater
ThinkNode_M8_room_server
```

`ThinkNode_M1_repeater` already declares external QSPI OTA. The plain MeshTower
repeater name is an alias for the SD primary, so this list must not be blindly
converted into 31 release removals. Aliases, full source options, board headers,
storage layout, and deployed target identities must be resolved first.

## Qualification before removing an image

Start by showing Full for ordinary installation and moving Reduced to advanced
or recovery selection. Preserve existing artifacts and update identities while
qualifying actual duplicate removal. For each candidate:

1. Build both profiles sequentially from the same source/toolchain, with the
   existing flash, RAM, capability, packaged-application, and OTA checks.
2. Extract the DFU application's `bin_file` from its ZIP manifest and compare
   its complete bytes, EndF identity/body hash, image length, and layout. Outer
   UF2/ZIP hashes alone can differ because of packaging and are insufficient.
3. If applications differ, measure the driver/capacity difference. For internal
   OTA, create exact-base deltas from representative installed Full and Reduced
   images and verify staging geometry, reconstruction, and the matched deployed
   bootloader. A passing local-install image does not prove a delta fits.
4. Change publication validation and fixtures deliberately before emitting one
   artifact. [`validate_nrf52_sensor_pairs()`](https://github.com/mikecarper/MeshCore/blob/08bf174ea30e2e075cdd9fc74111580662b461bb/scripts/package_cascade_release.py)
   currently requires exactly one qualified Full and one Reduced with matching
   target, hardware, version, source, and layout; it does not prove either member
   saves space or is needed. Preserve legacy endpoints needed by qualified chains.

Focused existing checks include `test/test_build_profiles.sh`,
`test/test_nrf52_ota_profiles.sh`, `test/test_ota_store_flash_nrf52_hybrid.py`,
`test/test_rak_storage_policy.py`, and the release-packaging tests. These check
policy and boundary behavior; they do not substitute for matched image and
exact-delta evidence. No PlatformIO process was started for this audit.

## Storage and bootloader choices that need real distinctions

[`OtaFlashLayout_nrf52.h`](https://github.com/mikecarper/MeshCore/blob/08bf174ea30e2e075cdd9fc74111580662b461bb/src/helpers/ota/OtaFlashLayout_nrf52.h) derives
internal staging space from the trusted live EndF application extent, rounded
to a 4 KiB page, and the effective bootloader ceiling.
[`OtaStoreFlashNrf52.cpp`](https://github.com/mikecarper/MeshCore/blob/08bf174ea30e2e075cdd9fc74111580662b461bb/src/helpers/ota/OtaStoreFlashNrf52.cpp) adds
64 KiB of retained RAM only with the matching `MOTARAMA` capability and at least
one available flash page. Its hybrid application path accepts deltas, not full
application containers. A **Full sensor firmware** can still be the destination
of a delta; the two uses of "Full" must not be confused.

The historical [RAK3401 chain](rak3401_mota_chain.md) proves tight exact-package
geometry under an older bootloader: multiple transitions have zero margin;
steps 1-9 were physically passed, while the replacement final step has offline
reconstruction and exact-bootloader simulation only. It does not compare the
current sensor pair and must not be generalized to all nRF52 boards.

External NOR/SD removes the internal container-staging bottleneck, but does not
increase executable internal flash or RAM. Existing runtime consolidation is
already available for qualified [RAK unified storage](../ota_nrf52_qspi.md) and
[MeshTower SD/internal fallback](../ota_meshtower_v2_sdcard.md). Keep the exact
NOR wiring, bootloader device/storage records, target IDs, and per-transfer
store selection. MeshTower's old internal-only identity needs local migration;
an alias does not authorize same-target LoRa replacement. Its internal fallback
can reject a delta that fits on SD.

The source explicitly rejects raw OTA QSPI sharing a chip with the QSPIFLASH
filesystem, and WisBlock OTA SPI sharing incompatible Ethernet/SD wiring.
RAK3401 flash and the 1 W radio need distinct chip selects and the explicit bus
handoff contract. Combining those recipes requires hardware/layout evidence,
not just runtime sensor switches. Extra-filesystem and bootloader-scratch
layouts likewise cannot be relabeled as the same OTA target.

## Other possible menu simplifications

The current ESP32 replay reports 174 Full choices, including the two newly
pulled Station G3 sensor recipes. Its evidence file
`out/esp32-full-audit-2026-10-06/wifi_review_current_consolidation.json` finds two
equivalent source-option pairs: Heltec V4 base/Expansion Kit OLED repeaters, and
their room-server recipes. Repeated identical I2C pin definitions are the only
semantic option difference, but their mOTA target IDs differ. Simplify selection
first; retain deployed update artifacts until an explicit migration is reviewed.
The Expansion Kit TFT Companion has different display/sensor wiring.

Pico W already has a combined USB/WiFi/BLE Companion recipe; it is a candidate
to replace transport-specific ordinary choices after fresh capacity and
transport qualification. This audit has no current qualifying build result.
STM32WL's retained flash reports support capacity tuning of its existing
256 KiB applications; they do not show a removable duplicate role. Repeater,
room-server, sensor, Companion/Terminal Chat, and KISS remain different
applications unless a separate combined application is designed and tested.
