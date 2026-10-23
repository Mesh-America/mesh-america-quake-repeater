<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/companion_cli_parity_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Companion hardware command parity, 2026-10-23

The audit baseline was `04c4fdb240318d0151947b8c11ce09a3e2aec65c`.
That revision already closed `get bootloader.ver`: Companion calls the same
board reader and preserves the bootloader's full version suffix. The follow-up
changes share the missing hardware diagnostics and SD command implementation.

This records source behavior and native regression tests, not hardware
qualification or a claim that every board or firmware type was built. Existing
local/remote authorization and platform/backend capability gates remain in use.

## Commands added after the audit

| Command | Behavior and limits | Implementation |
| --- | --- | --- |
| `get pwrmgt.support` | Reports actual board/build power-management support. | [Power diagnostics](../../src/helpers/CompanionPowerDiagnostics.h#L28) |
| `get pwrmgt.source` | Reports external/battery power when supported. External power does not establish that USB data is connected. | [Power diagnostics](../../src/helpers/CompanionPowerDiagnostics.h#L33) |
| `get pwrmgt.bootmv` | Reports the boot voltage sample, distinct from current battery voltage in `stats-core`. | [Power diagnostics](../../src/helpers/CompanionPowerDiagnostics.h#L34) |
| `get system.watchdog` | Reports actual running state where supported. Companion does not pretend to have Repeater's persisted watchdog switch; its setter explicitly reports unavailable. | [Watchdog diagnostics](../../src/helpers/CompanionPowerDiagnostics.h#L46) |
| `get rxps.wd` | Reports the radio driver's separate soft/hard recovery counts. These are not included in `stats-radio-diag`. | [Radio diagnostics](../../src/helpers/CompanionRadioDiagnostics.h#L17) |
| `get/set radio.rxps.rfrx_disabled` | Reads/changes the supported radio's RF RX policy for this boot. Retains driver ownership and receiver-restoration checks; does not persist a preference. | [Radio diagnostics](../../src/helpers/CompanionRadioDiagnostics.h#L31) |
| `power` | Reports current battery voltage and supported USB, solar, external-power and charger states. | [Power diagnostics](../../src/helpers/CompanionPowerDiagnostics.h#L15) |
| `clear stats` | Resets radio/mesh packet counters, sticky packet error flags and table duplicate counters. RXPS recovery history, queues and saved settings remain intact. | [Radio diagnostics](../../src/helpers/CompanionRadioDiagnostics.h#L23) |
| `get cad` / `get radio.cad` | Retains timing details and appends the channel-busy count. | [CAD diagnostics](../../src/helpers/CompanionRadioDiagnostics.h#L70) |

The watchdog setter requires more than an alias: Companion would need a saved
policy and feed-loop integration. An already running nRF52 watchdog cannot be
stopped directly; the existing
[disable path deliberately resets](../../src/helpers/NRF52Board.cpp#L328).

## Shared SD commands

All nRF52 builds that already enable `OTA_SD_STORE` use the same
[SD handler](../../src/helpers/SdCardCLI.cpp#L60) through
[CommonCLI](../../src/helpers/CommonCLI.cpp#L4033) or the Companion command router.
This adds no SD capability to unsupported boards.

| Command | Meaning |
| --- | --- |
| `get sdcard` / `get sdcard *` | Format/erase history for this boot. Bare `get sdcard` now follows CommonCLI's history reply; use `free` for space. |
| `get sdcard free` | Used and free space. |
| `get sdcard ls [page]` / `get sdcard dir [page]` | Paginated file listing; page must be 1-65535. |
| `get sdcard format` / `get sdcard erase` | Time since the corresponding successful maintenance operation, or `never`. These getters do not modify the card. |
| `set sdcard format [--force]` | Formats the card. |
| `set sdcard erase [--force]` | Erases and then formats the card. |

The setters preserve the existing five-minute per-action cooldown; `--force`
bypasses only that cooldown. Pending apply and unrelated occupied internal/NOR
update slots still block maintenance. The handler closes/checkpoints shared
archive work before card-wide changes and rebuilds the source view afterward
([guards and reset sequence](../../src/helpers/SdCardCLI.cpp#L99)).
RAK Ethernet ownership blocks space/list/maintenance access before allocating
an OTA context or changing update state
([bus exclusion](../../src/helpers/SdCardCLI.cpp#L22)); the card backend retains
its own bus and firmware-authorization checks. Failed context allocation or
card operations return an error without bypassing these checks.

The former Ethernet-only Companion SD query branch was removed. Ethernet's
own enable/disable admission and lifecycle callbacks remain separate.

## Existing commands and intentional distinctions

Companion already had `get pwrmgt.bootreason` / `powerlog`, USB debug/logging,
USB watchdog commands, sleep diagnostics, storage layout, ADC calibration,
regulator controls, and core/radio/packet statistics. Shared helper dispatch
must be checked before treating an absent literal command name as a gap.
ESP32 CPU frequency and power-test commands are also shared and remain
platform-specific.

`get/set radio.watchdog` is the
[Observer/MQTT inactivity policy](../../src/helpers/CommonCLI_Observer.cpp#L928),
not the universal nRF52 hardware watchdog. Repeater `get/set rx.watchdog` is a
separate [receive-inactivity policy](../../examples/simple_repeater/MyMesh.cpp#L13034).
Neither is copied into Companion without its underlying policy.

## SD validation

The shared production `.cpp` is compiled and executed under five native SD
profiles with address/undefined-behavior sanitizers. Tests cover malformed
commands, allocation failure, Ethernet ownership, card failures, bounded
replies, cooldown/clock wrap and history. Existing RAK seeder and context-handoff
suites also pass; the occupied-store matrix retains its negative regression
that detects destructive loss of an unrelated update.

Relevant suites: [SD CLI parity](../../test/test_sdcard_cli_parity.py),
[RAK seeder](../../test/test_rak15002_sd_seeder.py), and
[SD context handoff](../../test/test_rak_sd_context_handoff.py).
