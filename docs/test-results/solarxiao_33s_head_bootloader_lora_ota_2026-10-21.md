<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/solarxiao_33s_head_bootloader_lora_ota_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# SolarXiao 33S HEAD bootloader, LoRa OTA and repeater acceptance, 2026-10-21

The SolarXaio MPPT 12V LiFePO4 carrier with a Seeed XIAO nRF52840 and Ebyte
E22-900M33S passed a full application update over LoRa and subsequent repeater
acceptance on the Mercerwood bench. TX was configured to **-6 dBm** and
repeating enabled. Both settings survived the application update and a further
warm restart. Final core error flags were zero.

[Machine-readable results](solarxiao_33s_head_bootloader_lora_ota_2026-10-21.safe.json)
bind this result to the following revisions. These were the checked-out HEAD
revisions used for qualification; subsequent commits require separate testing.

| Component | Qualified revision or value |
| --- | --- |
| MeshCore source | [`efad0076816f7ba2293c68f56f8db18ac17344b9`](https://github.com/mikecarper/MeshCore/commit/efad0076816f7ba2293c68f56f8db18ac17344b9) |
| Application environment | `solarxiao_33S_repeater`, Full OTA package |
| Application version | `v1.18.0.1-halo-keymind-cascade-dev-efad0076` |
| OTAFIX bootloader source | [`b07255d4cdc601f1313e4cbe020caad3b5544821`](https://github.com/mikecarper/Adafruit_nRF52_Bootloader_OTAFIX/commit/b07255d4cdc601f1313e4cbe020caad3b5544821) |
| Bootloader profile | `xiao_nrf52840_ble`, board `28860044`, name `XIAO_DFU` |
| Bootloader packed test version | `0x02040B7E`, displayed as `OTAFIX2.4.11-preview.126` |
| Verified bootloader manifest CRC | `76EBABBF`; ABI 3, capabilities `0E` |
| SoftDevice | S140 7.3.0 |
| Application body hash | `6280E8156DB1042F` |
| Application image size | 578,752 bytes |
| Application image SHA-256 | `1a182b5338f7655b4fe057436768b84069c00aa151971c96d6c2b6f7c98e8524` |

The bootloader is the named HEAD build. Its preview version string retains the
2.4.11 base label; this campaign did not install the 2.4.11 release artifact.
The bootloader and SoftDevice were updated through serial DFU, followed by
restoration of the preceding application. Identity and saved settings remained
intact, and the running application confirmed QSPI bootloader-apply support.

## Full LoRa application update

A Heltec V4.3 Full Companion running source revision `2bd4cb4d` seeded the exact
Full `.mota` package. The destination started on application revision `e16db810`
with body hash `C9137AAAB9A5FCDB`. USB CLI controlled the target; application
image bytes traveled over LoRa. The target received **zero firmware bytes over
USB** during this application OTA test.

Both radios used a temporary 909.5 MHz, 500 kHz, SF7, CR 4/5 profile with a
32-symbol preamble. Target RX power saving was temporarily disabled for the
transfer; its configured TX remained -6 dBm. The source retained its saved
power-saving policy and TX setting.

Manifest `55E532FA` reached **283/283 blocks, ready to install**, with destination
session age 439 seconds. Host seeder logs showed reads of all 283 payload
blocks. After the install request, the target booted the expected version and
reported body hash `6280E8156DB1042F`. Its bootloader identity and CRC still
matched the qualified HEAD build.

A preliminary attempt to activate scheduled temporary channels through remote
administration failed before payload transfer. The completed test used local
USB CLI to activate the maintenance channel. Fully remote scheduled activation
and OTA with target RX power saving enabled remain unqualified by this run.

## Restart and repeater acceptance

Ten USB query cycles, three close/reopen cycles and a warm restart passed.
The version, body hash, board, role, public identity, TX setting and repeating
state remained consistent. An independent XIAO S3 WIO Companion then sent
three nonce-bound trace requests using the target's exact four-byte prefix
route on the normal channel.

| Round | Exact nonce and one-hop route | Target direct RX/TX delta | Trace elapsed | Receive error delta |
| --- | --- | --- | --- | --- |
| 1 | PASS | 1 / 1 | 0.498 s | 0 |
| 2 | PASS | 1 / 1 | 0.555 s | 0 |
| 3 | PASS | 1 / 1 | 0.536 s | 0 |

These traces establish reception and reply forwarding by the updated target.
The final core error flags were zero; the final packet counters reported zero
receive errors. The source and trace partner retained their saved settings.

## Final configuration and cleanup

- Repeater role, repeating `on`, TX `-6` dBm.
- Saved normal radio `910.5250244,62.5,7,5`; temporary radio inactive.
- RX power saving restored to `on,level=8,preamble=16,rx=39657,sleep=15975`.
- No active download or staged bootloader package; QSPI self-update support ready.
- Temporary seeder, source contact and SSH forwarding connection removed.
- USB endpoints closed after verification.

The first source cleanup check sampled the radio before its deferred restore
finished and reported an active window. A subsequent check confirmed temporary
radio inactive and exact equality with all saved source settings. The JSON
preserves that initial cleanup result and the completed restoration check.
