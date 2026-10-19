<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/hardware_validation_mercerwood_1_18_0_1_2026-10-19/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Mercerwood Full firmware testing, 2026-10-19

Source: `4e4f27a25a720c52ca0f5381b5e5834d75532cc6`
Version: `v1.18.0.1-halo-keymind-cascade-dev-4e4f27a2`

Builds: 13/13 targets, 15/15 profiles PASS. The two Reduced OTA profiles are compile-only; repeater hardware status uses Full OTA installation proof.
Expected radios: 13; USB radios observed: 12. USB enumeration does not establish physical presence or absence. Build success does not mean all 13 radios passed hardware testing.

| Board | Build | Flash | USB | BLE | RF | Bootloader |
| --- | --- | --- | --- | --- | --- | --- |
| Heltec V4.3 | PASS | PASS | PASS | PASS | unknown | n/a |
| RAK 3401 | PASS | PASS | runtime only PASS | n/a | n/a | C2 baseline PASS |
| LilyGo T-Deck | PASS | PASS | PASS | PASS | PASS | n/a |
| RAK WisMesh Tag | PASS | not enumerated | not enumerated | not enumerated | not enumerated | not enumerated |
| Heltec MeshPocket | PASS | PASS | PASS | PASS | PASS | C2 baseline PASS |
| SenseCAP Indicator | PASS | PASS | PASS | PASS | PASS | n/a |
| RAK 4631 | PASS | PASS | PASS | PASS | PASS | C2 baseline PASS |
| Heltec V3 | PASS | HEAD runtime PASS | PASS | PASS | PASS | n/a |
| Seeed XIAO ESP32-S3 | PASS | PASS | PASS | PASS | unknown | n/a |
| Seeed XIAO nRF52 | PASS | transfer PASS; runtime unqualified | unknown | unknown | unknown | C2 baseline PASS |
| Heltec T096 | PASS | PASS | PASS | PASS | PASS | C2 baseline PASS |
| Seeed T1000-E | PASS | PASS | PASS | FAIL | PASS | C2 baseline PASS |
| Heltec MeshTower SD | PASS | PASS | runtime only PASS | n/a | n/a | C2 baseline PASS |

Repeater rows cover Full OTA application/runtime verification only. Their runtime-only USB entries do not claim Companion 100/10, BLE or RF qualification.
C2 bootloader entries describe earlier source-qualified installation evidence, separately from current application results.

- Some expected radios were not enumerated in the selected USB inventory; this does not establish physical absence.
- T1000-E BLE remains unresolved until a completed current-source test passes.
- Heltec V4.3 had earlier USB/BLE passes, but later RF setup repeatedly rejected non-ASCII data before channels, leases or datagrams. Current transport behavior remains unresolved; RF qualification is pending.
- Seeed XIAO ESP32-S3 had earlier USB/BLE passes, but later RF setup repeatedly rejected non-ASCII data before channels, leases or datagrams. Current transport behavior remains unresolved; RF qualification is pending.
- XIAO nRF52 application transfer succeeded, but stable normal runtime and its USB/BLE/RF qualification remain unresolved.
- RAK WisMesh Tag is not USB-enumerated; its normal application and C2 bootloader campaign remain pending.

The V3's first 15-second discovery trial failed. Its separate 25-second scan trial is PASS; the earlier failure remains part of the record.

T1000-E's initial batch BLE trial failed. The explicit later retry is FAIL. The initial failure remains part of the record.

Seeed XIAO nRF52 completed the application transfer; recovery failed normal runtime verification. The failed recovery phase and original batch outcomes remain in the JSON trial history.

Seeed XIAO nRF52: The normal HEAD application transfer succeeded, but normal HEAD runtime was not verified within the required 75-second window. Runtime qualification remains incomplete. Bootloader baseline evidence is reported separately.

The measured V3 92-contact refresh median was 3.347882 s at 32.560 kbit/s, versus 6.191396 s at 17.606 kbit/s for the earlier firmware. These are protocol throughput measurements on one V3/Linux connection, not BLE PHY rates or phone/full-app refresh claims. [Measured results](https://mikecarper.github.io/MeshCore/test-results/companion_ble_refresh_2026-10-19/).

The inventory observed 12 distinct USB identities during a 10-second read-only window, including the cycling XIAO nRF52. This does not mean 12 stable ports.

This is a partial campaign report: 9/11 Companion USB qualifications, 8/11 BLE qualifications and 6 two-way RF links (7 boards including the RAK hub) passed. The full campaign is incomplete.

USB qualification used 100 persistent query cycles and 10 reopen checks, owned-contact CRUD and warm reboot, plus RX-only radio2 overlap-warning and three-decimal frequency-suggestion trials. BLE passes required three 30-second sessions. RF passes required exact two-way zero-hop DEV datagrams and owned-channel/radio-lease cleanup; they do not qualify text delivery, range, cold boot, phone interoperability or every firmware feature.

RF setup attempts with no completed delivery are retained separately; they do not count as failed deliveries.

MeshPocket previously reported error flag 8. Receive silence is a hypothesis, not a confirmed radio fault. A controlled warm reboot with flushed command delivery returned clean core flags, and its later two-way RAK RF test passed. The earlier unconfirmed reboot attempt and incomplete RF setup remain part of the history.

The T1000-E retry discovered the USB-bound advertisement, but pairing failed with a D-Bus error before any completed sessions. The NUS public key was not verified. Its initial batch discovery failure remains retained; BLE qualification is unresolved.

The retained pairing reason was Page Timeout.

V4.3 history retains 4 non-ASCII RF setup aborts and one separate failed USB setup diagnosis. An intervening guarded classification completed a clean normal HEAD handshake and closed its port; it did not qualify RF or run a transition drain.

The final read-only gateway check verified the active service held the RAK 3401 primary CDC0 interface.

The unit-test workflow passed for the measured firmware source `4e4f27a2`: [GitHub run](https://github.com/mikecarper/MeshCore/actions/runs/39328768327).

[Machine-readable results](hardware_validation_mercerwood_1_18_0_1_2026-10-19.safe.json).
