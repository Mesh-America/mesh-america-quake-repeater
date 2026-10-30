<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/stm32_companion_help_2026-10-23/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# STM32WL Companion help packing, 23 October 2026

Small STM32WL USB Companions now use the existing packed help producer with a
256-byte history. Every command, option and terminal suffix is retained. The
same feature-gated `CompanionHelp.inc` supplies the packed and ordinary output.
nRF52 RAK Full keeps its 2,048-byte history; ESP32 retains its ordinary help
printing path. Contact/channel limits and the application/filesystem boundary
are unchanged.

Only the selected `CompanionHelpPacked.cpp` is compiled as C++17. A source-role
policy registers that override for STM32WL Companion builds, excludes other
roles and reuses the existing per-object helper without installing nRF52
trims. Other project sources and framework/library language standards remain
unchanged. The final producer also requires the STM32WL platform and text
terminal capability.

Native tests compare the STM32 output with the preceding ordinary-printing
bytes, including both USB and network terminal suffixes. They exercise short,
zero and invalid writes, overlapping matches, ring wrap, malformed tokens and
a match farther back than the selected history. The STM32 profile's USB help
remains 1,908 bytes including its terminal suffix. Its SHA-256 is
`9e587ac9f287c8f8fe64fe5c899fe635b6de5d6cf436c4c43a27ffd4add42474`.
C++11 callers link and execute the actual C++17 producer under address and
undefined-behavior sanitizers for both STM32WL and RAK Full.

The standalone Cortex-M4 object comparison saves 733 bytes including the
decoder and its data, before whole-firmware LTO effects. Emitted producer and
helper frames total 384 bytes; a 512-byte caller/output reserve keeps that
local estimate at 896 bytes within the existing 1,024-byte minimum stack
allowance. This is compiler frame accounting, excluding physical interrupt
high-water. The complete firmware's linked size is a separate build check.

Complete builds at `5b20bf37` passed sequentially with the Cascade profile and
unchanged flash boundaries. All four USB Companions also passed the canonical
OTA packaging and runtime RAM checks:

| Target | Linked flash used / limit | Flash remaining |
| --- | --- | --- |
| RAK 3x72 USB Companion | 228,920 / 229,376 bytes | 456 bytes |
| Wio E5 Mini USB Companion | 228,736 / 229,376 bytes | 640 bytes |
| Wio E5 USB Companion | 228,716 / 229,376 bytes | 660 bytes |
| Tiny Relay USB Companion | 228,784 / 229,376 bytes | 592 bytes |

The Wio E5 Mini repeater also passed its cable-only build and runtime RAM
checks at 245,356 / 245,760 flash bytes, leaving 404 bytes. These integrated
STM32WL targets expose no supported saved radio-switch tuning features; the
unavailable machinery is omitted without changing their radio commands or
stored profiles. These are build checks, not physical device qualification.
