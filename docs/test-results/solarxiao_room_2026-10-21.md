# SolarXiao Room Server power profiles and history, 2026-10-21

The canonical SolarXiao QSPI OTA Room Server builds now initialize and service
the native power interface. Both 30S and 33S support the same `auto`, `basic`
and `mppt` profiles as Repeater, including saved overrides, native telemetry
and authenticated administrator commands. Basic still supplies only existing
XIAO battery voltage and MCU temperature; no Base/Advanced measurements were
invented.

The earlier size failure used a legacy plain Room recipe. This run qualifies
the existing `solarxiao_30S_room_server_lora_ota` and
`solarxiao_33S_room_server_lora_ota` recipes with Full and Reduced sensors.
Both fit the unchanged 757,760-byte OTAFIX application region. No features,
client capacities or flash reservations were reduced to make them fit.
Plain Room compatibility/recovery targets remain separate and unchanged.

## Qualified source and artifacts

Source:
[`1d2fb6a1b471f2984a5a4133854cad4b52150337`](https://github.com/mikecarper/MeshCore/commit/1d2fb6a1b471f2984a5a4133854cad4b52150337).
Version: `v1.18.0.1-halo-keymind-cascade-dev-1d2fb6a1`.

| Target | Profile | Application bytes | EndF body hash |
| --- | --- | --- | --- |
| `solarxiao_33S_room_server_lora_ota` | Full | 524,424 | `761289FD9CEFE79B` |
| `solarxiao_33S_room_server_lora_ota` | Reduced | 494,888 | `9CA04F37C960797A` |
| `solarxiao_30S_room_server_lora_ota` | Full | 524,424 | `AB4F7D7F85872201` |
| `solarxiao_30S_room_server_lora_ota` | Reduced | 494,888 | `FBD9FAA560F5D0CE` |
| `solarxiao_33S_repeater` | Full regression | 598,824 | `DEB7475A4B4B0BBC` |
| `solarxiao_33S_repeater` | Reduced regression | 568,828 | `8CDBFB5FA2615124` |

All six builds passed DFU/UF2, linked capability and runtime-memory
qualification. Room Full/Reduced have 156,352/157,984 internal bytes available
against 65,280 required; Repeater has 150,576/152,224 against 82,752 required.
The model now explicitly reserves 5,792 bytes for capped I2C voltage history
and allocator overhead, retaining the previous general sensor allowance.

Independent package checks verified application version, body length/hash,
artifact hashes, three power modes, native power marker and self/history
responses. Room packages also contain persistent Room history and board
commands. The linked Room code retains posting, access control, mailbox,
board articles and persistent post history. Existing Room target IDs remain
30S `0x5bb567cd` and 33S `0xa8cb8e8b`; their hardware IDs remain
`solarxiao_30S`/`solarxiao_33S`. Repeater keeps `0x3caf966e`.

## History correction and host checks

History previously configured channels once before Auto's first probe. An
MPPT discovered later could therefore provide live telemetry but never gain
voltage-history storage. The shared driver now reserves history IDs 2..5 at
boot without any bus access. Only active, valid readings produce samples;
empty channels remain absent from populated history results. Late INA260
detection, later charger input power and Basic-to-MPPT changes can supply
samples without rebooting or clearing other sensor history. This fixes both
Room and Repeater.

Four native channels allocate 1,440 bytes; the shared 16-channel cap limits
native plus optional history to 5,760 bytes. The new budget test compiles the
real history class and binds that allocation to the RAM policy. It also checks
disabled-history/native cases and unrelated platforms.

Passing checks include:

- 30 SolarXiao methods: 19 carrier, 3 core power, 5 Room integration and 3 memory
  tests. Native harnesses use ASan/UBSan.
- Actual Room telemetry/history methods, shared adapter and environmental
  sensor methods: delayed detection/VIN, preserved history across mode changes,
  environmental/guest permissions and complete LPP replies for capacities 4..184.
- Actual administrator gate, remote timestamp-zero denial of USB-only actions,
  prefixed reply bounds, startup/null-persistent-FS/history propagation and loop
  hooks. Canonical feature inheritance leaves legacy recovery/Companion unchanged.
- Six XIAO startup/battery checks; two pinned official Room-app compatibility
  methods for login and received posts; persistent Room history integration
  with 199 scenarios on each of five simulated platforms.
- All 49 existing RAM-policy methods, the build-profile suite and the nRF52
  Full/Reduced OTA profile suite.

PlatformIO ran one process at a time. Final packages and logs are retained at
`/home/mesh/hwtest/solarxiao-room-20261021/final-firmware/` and its parent.
The [validation record](solarxiao_room_2026-10-21.safe.json) contains exact hashes.

## Deployment scope

This is host/build qualification, not physical Room acceptance. No device was
flashed, no Room boot/soak or RF test was run, and no LoRa firmware transfer was
performed for this image. SEA Sherwood remains unreachable and unchanged.
The matching board/storage-aware OTAFIX bootloader is required for these Room
targets; the existing bootloader/scratch layout and 30S/33S PA settings were
preserved. See the [controls guide](../solarxiao_power.md) for commands and
target selection.
