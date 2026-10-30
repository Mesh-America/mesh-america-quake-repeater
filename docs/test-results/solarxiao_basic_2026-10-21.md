<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/solarxiao_basic_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# SolarXiao three power profiles, 2026-10-21

Base and Advanced share the same onboard power telemetry: XIAO battery voltage
and MCU temperature. Their analog charger designs differ, but the published
layouts expose no additional digital charger measurements or controls. The
firmware now combines them into one Basic power profile without claiming which
charger is fitted. Additional power measurements require added hardware/wiring.

There are three canonical choices:

- `auto`: verify INA260 to enable MPPT; otherwise self-only, retrying.
- `basic`: Base/Advanced self readings with native power-chip access disabled.
- `mppt`: manual MPPT override, retaining independent charger write checks.

Auto remains the default without a saved selection. Old `base` and `advanced`
command values remain compatibility aliases for `basic`, not separate modes.
Readbacks and help show only the three canonical choices. Existing Advanced
record value 1 and Base value 3 both load as Basic without a startup write.
New Basic/alias saves use value 1. MPPT and Auto retain values 0 and 2.

Radio target choice remains independent: select the existing 30S/33S target for
the fitted E22 module. No RF settings, PA limits, OTA identities, bootloader,
flash layout, battery protection or automatic detection behavior changed.

## Qualified source and packages

Application source:
[`aa91fffae41465ba932f069f2a45e2a3ae1c7ad4`](https://github.com/mikecarper/MeshCore/commit/aa91fffae41465ba932f069f2a45e2a3ae1c7ad4).
Version: `v1.18.0.1-halo-keymind-cascade-dev-aa91fffa`.

| Target | Profile | Application bytes | EndF body hash |
| --- | --- | --- | --- |
| `solarxiao_33S_repeater` | Full | 598,824 | `37EE3060D73CAB2E` |
| `solarxiao_33S_repeater` | Reduced | 568,828 | `2174A0D9CB1EA7B9` |
| `solarxiao_30S_repeater` | Full | 598,824 | `3525D6629B234891` |
| `solarxiao_30S_repeater` | Reduced | 568,828 | `8037A8127A7D324A` |

All four DFU/UF2 builds passed linked capability, packaging and runtime memory
checks. Full has 150,576 internal bytes available; Reduced has 152,224, against
76,960 required. Independent package checks verified version, EndF body length,
body hash, unchanged target/hardware IDs, artifact hashes and linked Basic
capabilities. Every application contains the three-option help and omits the
old four-option help. PlatformIO ran one process at a time.

## Host acceptance and scope

All 28 checks passed: 19 carrier methods, 3 existing power methods and 6 XIAO
startup/battery safety checks. Native harnesses use ASan/UBSan. Compatibility
tests cover every old record value 0..3, both aliases, canonical Basic saves,
identical actual-adapter gating and no startup rewrite. Every out-of-range
record value 4..255 fails closed with no native bus access.

The actual adapter retains live self readings in Basic mode while native
commands, periodic access, telemetry and voltage-history calls make no native
bus calls. Existing detection/retry, timer-wrap/long-uptime replay, persistence
fault, identity, permission, parser-boundary, canary and history checks pass.

These are host/build results only. No device was flashed and no physical Auto,
radio, charger, boot/soak or LoRa OTA test was performed for this image. SEA
Sherwood remains unreachable and unchanged. Earlier hardware reports apply
only to their named firmware revisions.

See the [validation record](solarxiao_basic_2026-10-21.safe.json) for package
hashes and the [controls guide](../solarxiao_power.md) for hardware sources and
commands. Packages and logs are retained under
`/home/mesh/hwtest/solarxiao-basic-20261021/`.
