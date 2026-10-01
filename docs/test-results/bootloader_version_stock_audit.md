# Stock nRF52 bootloader version audit

Checked **2026-09-29**, against the 40 nRF52 variant families resolving to 26
board configurations in this checkout. This concerns `get bootloader.ver`, not
bootloader installation or OTA eligibility. No devices were flashed, and no
features, storage sizes, or partitions were changed.

## Result

The real firmware reader successfully reads **26 distinct manufacturer-published
bootloader images** from 32 artifact records, including older RAK revisions,
current and historical LilyGO images, and vendor HEX, UF2 and DFU ZIP packages.
Repeated copies and identical normalized bootloader images are counted once.
These are publicly supplied stock/recovery images, **not proof that every
manufacturing batch shipped identical bytes**. No untouched live unit was read
in this audit.

One format gap was fixed: Seeed's T1000-E **LoRaWAN development-board** bootloader
declares `UF2 Bootloader 1.00`. The reader now accepts that two-component version
and returns `1.00` unchanged. It does not invent `1.00.0`. That development image
is separate from Seeed's Meshtastic/MeshCore recovery image, which reports
`0.9.1-5-g488711a` and already worked.

All other tested images already expose a readable UF2 bootloader record.
Generic bare dotted-number searches remain deliberately unsupported: TinyUSB,
nrfx, and SoftDevice can embed their own versions inside the same bootloader.
The bounded standalone fallback still requires the explicit OTAFIX version
shape. Ambiguous records, invalid vectors, and corrupt canonical OTAFIX metadata
retain the existing rejection rules.

## Published images actually tested

The exact source URLs, download hashes, normalized-image hashes, extraction
layout and expected strings are pinned in
[`stock_images.json`](https://github.com/mikecarper/MeshCore/blob/keymindCascade/test/fixtures/nrf52_bootloader_version/stock_images.json).

| Manufacturer image family | Version captured from the image |
| --- | --- |
| RAK4631/RAK4630 Arduino bootloader, historical through current | `0.3.2-109-gd6b28e6`, `0.4.1-13-g5e6690e-dirty`, `0.4.2`, `0.4.3`, `0.4.4` |
| Heltec HT-n5262, SDK and T114 vendor recovery HEX | `0.9.0-2-g836c8dc-dirty` |
| LilyGO T-Echo | `0.6.1-2-g1224915` |
| LilyGO T-Echo Lite, Card, T-Impulse Plus (including historical builds) | `0.9.2-dirty` |
| Seeed XIAO nRF52840 and Sense | `0.6.1` |
| Seeed XIAO nRF52840 Plus and Sense Plus | `0.9.2-29-g6a9a6a3` |
| Seeed Wio Tracker 1110 SDK/conversion bootloader | `0.6.2-26-g949425a-dirty` |
| Seeed Wio Tracker L1 vendor recovery ZIP | `0.7.0-22-g277a0c8` |
| Seeed T1000-E Meshtastic/MeshCore recovery ZIP | `0.9.1-5-g488711a` |
| Seeed T1000-E LoRaWAN development-board HEX | `1.00` (newly supported) |
| Seeed MeshTracker X1 recovery ZIP | `0.10.0-18-gb93789f` |
| MTools Tec MeshTiny vendor bootloader UF2 | `0.4.5` |
| BQ/Unit Engineering Nano G2 Ultra vendor HEX ZIP | `0.6.4-dirty` |
| Muzi Works R1 Neo release HEX | `0.9.2-31-g990aa7f-dirty` |

**Use the embedded version, not the filename.** For example, Seeed's XIAO file
named `...bootloader-0.6.2...hex` reports `0.6.1`, and its L1 ZIP named
`...bootloader-0.10.0...zip` reports `0.7.0-22-g277a0c8`. These are actual tested
bytes, not renamed or inferred release numbers.

All these normalized images use the Adafruit nRF52840 `F4000..FE000` bootloader
window. HEX/UF2 address records identify the bytes. The boot-only Seeed DFU
packages omit MBR/UICR address words; their bootloader binary is extracted using
the manifest's `sd_size`/`bl_size` and the
[Adafruit nRF52840 linker layout](https://github.com/adafruit/Adafruit_nRF52_Bootloader/blob/master/linker/nrf52840.ld).
The runtime reader independently selects the installed MBR/UICR boot address;
this audit does not hardcode that layout into the firmware getter.

## Coverage of every variant family

- **Image verified:** a published bootloader for that named product/module was
  tested. Factory batch identification still requires reading the actual unit.
- **Representative only:** a related module/SDK bootloader was tested; its exact
  factory image was not obtained. Shared build configuration alone does not
  establish identical factory bootloaders.
- **Unverified:** no accessible factory bootloader image was obtained. This is
  not a demonstrated reader failure.

| Variant family | Status | Evidence or remaining gap |
| --- | --- | --- |
| `gat562_30s_mesh_kit` | Unverified | GAT documentation/firmware repository checked; no product-specific stock bootloader found. |
| `gat562_mesh_evb_pro` | Unverified | Same GAT gap; RAK board configuration is not factory-image proof. |
| `gat562_mesh_tracker_pro` | Unverified | Same GAT gap; custom vendor/OTAFIX builds also exist. |
| `gat562_mesh_watch13` | Unverified | Same GAT gap. |
| `heltec_mesh_solar` | Representative only | HT-n5262 SDK image passes; Solar downloads found application images, not a board-specific stock bootloader. |
| `heltec_t096` | Representative only | HT-n5262 SDK image passes; T096 factory revision not established. |
| `heltec_t1` | Representative only | SDK image passes; vendor F&T archive contains application-only UF2s. |
| `heltec_t114` | Image verified | Both SDK HEX and T114-specific vendor recovery HEX pass. |
| `heltec_tower_v2` | Representative only | SDK image passes; vendor matching-firmware archive contains applications, not the stock bootloader. |
| `ikoka_handheld_nrf` | Representative only | XIAO board configuration; XIAO module images pass, exact installed factory image not obtained. |
| `ikoka_nano_nrf` | Representative only | Same XIAO representative coverage. |
| `ikoka_stick_nrf` | Representative only | Same XIAO representative coverage. |
| `keepteen_lt1` | Unverified | Manufacturer product/download search did not yield a factory bootloader binary. |
| `lilygo_t_impulse_plus` | Image verified | Both historical and newer vendor bootloader HEX images pass. |
| `lilygo_techo` | Image verified | Vendor T-Echo bootloader passes. |
| `lilygo_techo_card` | Image verified | Three distinct vendor historical/current bootloader images pass. NFC UICR repair application excluded. |
| `lilygo_techo_lite` | Image verified | Vendor bootloader HEX passes. |
| `mesh_pocket` | Representative only | HT-n5262 SDK image passes; exact Pocket factory revision not established. |
| `meshtiny` | Image verified | Direct manufacturer bootloader UF2 passes; newer ADV/factory revisions require their actual image. |
| `meshtracker_x1` | Image verified | Seeed product-specific recovery ZIP passes. |
| `minewsemi_me25ls01` | Unverified | Manufacturer module page lists firmware as none; no stock bootloader binary found. OEM/dev-kit installations can differ. |
| `muzi_base` | Unverified | Manufacturer publishes bootloader source, but its release assets found were for R1 Neo, not BASE. |
| `muziworks_r1_neo` | Image verified | Manufacturer R1 Neo release HEX passes; do not substitute a generic RAK version. |
| `nano_g2_ultra` | Image verified | Manufacturer's preinstalled-bootloader recovery HEX ZIP passes. |
| `promicro` | Unverified | Nologo documents a Nice!Nano UF2 drive; its linked download requires Baidu access. Generic clones need separate factory images. |
| `rak3401` | Representative only | RAK4631 Arduino images pass; RAK3401-specific untouched image not obtained. |
| `rak4631` | Image verified | Five distinct published stock Arduino bootloader revisions pass. RAK4631-R/RUI3 is a different bootloader family. |
| `rak_wismesh_tag` | Representative only | RAK core images pass; exact Tag factory image not obtained. |
| `sensecap_solar` | Representative only | Seeed documentation identifies XIAO DFU; XIAO images pass, exact Solar factory image not obtained. |
| `t1000-e` | Image verified | Both vendor recovery ZIP and separate LoRaWAN development-board HEX pass. |
| `thinknode_m1` | Unverified | Manufacturer repository checked; no factory bootloader binary found. |
| `thinknode_m3` | Unverified | Published factory UF2 is application-only (`26000..52BFF`), not a bootloader image. |
| `thinknode_m4` | Unverified | Published factory UF2 is application-only (`26000..521FF`). |
| `thinknode_m6` | Unverified | Published factory UF2 is application-only (`26000..46CFF`). |
| `thinknode_m8` | Unverified | No accessible product-specific factory bootloader binary found. |
| `wio-tracker-l1` | Image verified | Seeed's L1 recovery ZIP passes. |
| `wio-tracker-l1-1w` | Representative only | L1 recovery image passes; exact 1W/ADV factory revision not established. |
| `wio-tracker-l1-eink` | Representative only | L1 recovery image passes; exact e-ink factory revision not established. |
| `wio_wm1110` | Representative only | Published Wio Tracker 1110 and XIAO SDK images pass; the variant's XIAO config does not prove the shipped module's image. |
| `xiao_nrf52` | Image verified | XIAO, Sense, Plus and Sense Plus vendor images pass. |

Representative/unverified products use the same shared reader and should report
a version **if their installed bootloader exposes one of the recognized records**.
There is no evidence yet for claiming an exact version or success on every
untouched unit. ESP32, RP2040 and STM32 are outside this nRF52 flash reader;
their getters were not changed and this report does not claim stock-version
capture on those architectures.

## Reproduce the artifact tests

Normal tests are offline and include all observed version strings, malformed and
conflicting versions, dependency-version false positives, region/vector bounds,
and the existing OTAFIX metadata/CRC/fallback cases:

```sh
python3 test/test_nrf52_bootloader_version.py -v
```

To replay the real images, download each `url` in `stock_images.json` into a
cache directory using its `file` name, then run:

```sh
MESHCORE_STOCK_BOOTLOADER_CACHE=/absolute/path/to/cache \
  python3 test/test_nrf52_bootloader_version.py -v
```

This checks the exact download SHA-256, extracts only the bootloader window,
checks the normalized-image SHA-256, and invokes the actual C++ reader with an
exact expected version. It never downloads automatically or flashes a device.
The ordinary regression cases cover every captured format even without the
optional cached artifacts. RAK4631 and T1000-E repeater firmware builds passed.

## What is needed to close the remaining gaps

For each untouched unit, collect its DFU drive's **`INFO_UF2.TXT`** if present.
To prove the application's flash reader can capture that exact revision, also
obtain a read-only bootloader dump plus the MBR word at `0xFF8`, UICR `NRFFW[0]`,
and flash geometry (or a full vendor HEX including those address records).
Keep the bootloader unchanged while collecting this evidence. Only the identified
bootloader region is needed; private application keys/configuration are not.
If no version bytes or startup register value exist, report `unknown`; a regex
cannot recover a version that was never embedded.

## Manufacturer sources

- [RAK stock bootloader catalog](https://github.com/RAKWireless/WisBlock/tree/master/bootloader/RAK4630)
- [Heltec SDK](https://github.com/HelTecAutomation/Heltec_nRF52), [vendor downloads](https://resource.heltec.cn/download)
- LilyGO [T-Echo](https://github.com/Xinyuan-LilyGO/T-Echo), [T-Echo Lite](https://github.com/Xinyuan-LilyGO/T-Echo-Lite), [T-Echo Card](https://github.com/Xinyuan-LilyGO/T-Echo-Card), [T-Impulse Plus](https://github.com/Xinyuan-LilyGO/T-Impulse-Plus)
- [Seeed Arduino bootloader catalog](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/tree/master/bootloader), [T1000-E recovery](https://wiki.seeedstudio.com/sensecap_t1000_e/), [T1000-E development board](https://github.com/Seeed-Studio/Seeed-Tracker-T1000-E-for-LoRaWAN-dev-board), [MeshTracker X1 recovery](https://wiki.seeedstudio.com/sensecap_meshtracker_x1_meshcore/), [Wio L1 bootloader guidance](https://wiki.seeedstudio.com/get_started_with_other_mesh_firmware/)
- [MeshTiny manufacturer bootloader download](https://shop.mtoolstec.com/bootloader-update-on-meshtiny.html)
- [Nano G2 Ultra manufacturer bootloader documentation](https://wiki.bqvoy.com/en/meshtastic/nano-g2-ultra)
- [Muzi bootloader source/releases](https://github.com/muzi-works/Adafruit_nRF52_Bootloader), [BASE source guidance](https://muzi.works/pages/base-system-downloads)
- [GAT manufacturer documentation](https://github.com/gat-iot/GAT562-family), [Elecrow manufacturer repositories](https://github.com/Elecrow-RD), [Keepteen](https://www.keepteen.com/)
- [Nologo ProMicro documentation](https://www.nologo.tech/product/otherboard/NRF52840.html)
- [Minewsemi ME25LS01 module specifications](https://en.minewsemi.com/lora-module/lr1110-nrf52840-me25LS01)
