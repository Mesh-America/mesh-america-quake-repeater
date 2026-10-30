<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/companion_ble_refresh_2026-10-19/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Companion Bluetooth contact refresh, 2026-10-19

The production Heltec V3 Full Companion refreshed 92 contacts in a median
**3.347882 seconds at 32.560 kbit/s**, compared with **6.191396 seconds at
17.606 kbit/s** for the earlier 60 ms firmware. All five complete refreshes and
the 46-contact incremental refresh passed exact-record validation in each run.
The new firmware reduced median complete-refresh time by **45.9%** on this
Mercerwood Pi connection.

Measured production source:
[`4e4f27a25a720c52ca0f5381b5e5834d75532cc6`](https://github.com/mikecarper/MeshCore/commit/4e4f27a25a720c52ca0f5381b5e5834d75532cc6),
version `v1.18.0.1-halo-keymind-cascade-dev-4e4f27a2`, target
`Heltec_v3_companion_radio_full`. This was the normal Full build, with no BLE
benchmark override. These results measure contact synchronization on one V3
and one Linux central; phone performance and complete application refreshes
remain untested.

## Production behavior

The modern NimBLE-Arduino adapter now spaces notification attempts by at least
7 ms. Legacy NimBLE and Bluedroid retain their 60 ms setting. After the first
successful encrypted, authenticated and bonded connection callback for a link,
the modern adapter requests a 15-30 ms connection interval, zero peripheral
latency and a four-second supervision timeout. It makes this request once per
authenticated link. The central chooses the accepted connection parameters.

Required replies retain the existing bounded queues, notification-subscription
and negotiated-MTU gates, retry behavior and stalled-link recovery. Each
notification carries one complete protocol frame. Failed notification attempts
retain the frame; successful queue acceptance removes it without waiting for a
later callback. Contact-stream production retains its existing 5 ms pacing.
The change preserves the Full feature configuration and contact capacities.

## Hardware method and results

The same physical V3, Pi controller and 92 owned synthetic contacts were used
for both firmware revisions. V3 Full has capacity for 100 contacts; eight slots
were reserved. The fixture used zero path bytes and two modification timestamps
so the incremental filter selected exactly 46 records. The complete fixture
record-set hashes agree across both runs. Application-only upgrades preserved
the contact fixture and node identity.

After the comparison, all 92 owned test contacts were removed. A fresh USB
session verified their absence and that the other contact records were unchanged.

The earlier firmware was
[`fcc4714e2b1294a0d76c0aab4fa3b95b1609b3d0`](https://github.com/mikecarper/MeshCore/commit/fcc4714e2b1294a0d76c0aab4fa3b95b1609b3d0).
Its comparison run followed a controlled warm boot, recorded separately from
the BLE measurement. That preparatory check verified the same node, all 92
persisted contacts and a reset uptime without core errors. The result measures the
combined firmware revisions, including the intervening contact-storage fixes;
it does not isolate the contribution of each individual change.

| Measurement | Earlier 60 ms firmware | Production `4e4f27a2` |
| --- | ---: | ---: |
| Complete refreshes passed | 5/5 | 5/5 |
| Exact contacts per complete refresh | 92 | 92 |
| Median request-to-END time | 6.191396 s | 3.347882 s |
| Complete-refresh time range | 6.137166-6.331489 s | 3.342054-3.435741 s |
| Median protocol throughput | 17.606 kbit/s | 32.560 kbit/s |
| Incremental contacts verified | 46 | 46 |
| Incremental request-to-END time | 3.259745 s | 1.696429 s |
| Incremental protocol throughput | 16.733 kbit/s | 32.152 kbit/s |

Each stream had to return a valid start header, the declared complete count,
unique complete records, every expected owned record byte-for-byte, and a valid
END watermark. Incremental results had to equal the timestamp-filtered complete
inventory. All streams had zero duplicate contacts or unexpected restarts.
The qualifier also checked the complete firmware version and public identity
against USB, authenticated NUS access, and monotonic device uptime.

Throughput is application-protocol bytes divided by host-observed time from
the GET_CONTACTS write through the validated END notification. One complete
refresh contains 92 records of 148 bytes plus ten header/END bytes: 13,626 bytes.
The figures include request latency and protocol framing. Unsolicited pushes
are excluded from the byte total. These values are not BLE PHY bit rates.

## Observed connection and controller limits

Metadata collected during the normal production run showed the connection
start at 48.75 ms, latency zero and a 420 ms supervision timeout, then accept
**30 ms, latency zero and a 4,000 ms supervision timeout**. The complete-refresh
contact callback gap medians were 30.79-30.87 ms; per-run p95 gaps were
56.97-58.40 ms. Callback gaps include host/controller scheduling and are not
direct radio airtime measurements.

The Pi controller returned LE feature bytes `[31, 0, 0, 0, 0, 0, 0, 0]` from
HCI opcode `0x2003`: its Data Length Extension and LE 2M PHY feature bits were
both zero. HCI LE Read Maximum Data Length (`0x202f`) returned status `0x01`,
unsupported command. This hardware result establishes the controller's reported
capabilities; no DLE support was inferred from its Bluetooth version. A newer
controller or phone may behave differently and requires separate measurement.

The monitor collector emitted only numeric connection/update, data-length and
PHY fields. Raw monitor captures, addresses, keys, passkeys and contact records
were not saved in the shareable evidence.

## Native and build evidence

All six cases in
[`test_nimble_companion.py`](https://github.com/mikecarper/MeshCore/blob/4e4f27a25a720c52ca0f5381b5e5834d75532cc6/test/test_nimble_companion.py)
passed. Four real-adapter configurations, including the production default and
explicit 7/15/60 ms lab settings, execute a 128-record stream under controller
rejection, queue pressure, notification-subscription changes and small-MTU
pauses. They verify exact ordered delivery, retry retention, bounded queues,
interval boundaries, timer wrap and connection-parameter request gating. The
other two cases verify modern/legacy pacing policy and reject unauthorized or
out-of-range benchmark overrides. These are native tests, separate from the
92-contact hardware measurements.

All 13 campaign targets compiled and passed their memory admission checks at
the measured production source. The 11 Full Companions were V3, T1000-E,
RAK4631, T096 FEM on, Mesh Pocket, XIAO nRF52, WisMesh Tag, V4.3 FEM off,
T-Deck, XIAO S3 WIO and SenseCAP Indicator. RAK3401 and MeshTower SD repeater
targets also passed, with full/reduced OTA packages. All 15 resulting capability
manifests were verified. Compilation covers this build set; it does not qualify
every board or every Full feature on hardware.

The retained V3 ELF SHA-256 is
`a05c0cd6d70a8146296d9b6c3edbe3e8602fe05901b4d05759454cf61ba7e902`.
It matches the passed Full memory manifest, whose application, merged image,
capability manifest and license hashes also matched. Disassembly confirms the
7 ms comparisons in `isWriteBusy()` and `checkRecvFrame()`, and the authenticated
`updateConnParams` call with interval units `12/24`, latency `0`, timeout `400`
and connection-event length hints `0/0`. This establishes the linked code;
the monitor evidence above establishes the parameters accepted in this run.

## Retained safe evidence

These artifact names and SHA-256 hashes identify the evidence used for this
page. The page contains no private device identifiers or raw contact records.

| Artifact | SHA-256 |
| --- | --- |
| `v3-equivalent-warmboot.safe.json` | `6d816656a4ff5d2dc22f2175026078bb6b487445acbcc51a70fb3cd51cf87838` |
| `v3-60ms-92-after-warmboot-retry.safe.json` | `41a06fdb63cb63c08d63ca09be78c12e5997bec7fccc2a4a164acda56fd0fabf` |
| `v3-production-fast-92.safe.json` | `d0633f82862322d48194ccdb99a030a600365f1ecd3da729f32614aa80beb510` |
| `v3-production-fast-link.safe.jsonl` | `fdac4c5d0ed73d2c1e3d1e37c2ef02ecc5831d7cb791099da1e3c97493825e64` |
| `pi-hci-capabilities.safe.json` | `7c103253e305b2345dfcbb9170faad4b67c91df5a475536798e1bf48d60b7980` |
| `v3-linked-ble-proof.safe.json` | `cc04c5b0547a9911b9fb3a41fa33140c4647565b27d32c4b51c3d266c6ef7fbb` |
| `v3-owned-cleanup.safe.json` | `c1c7e59c30bf0c2e8bd3097007a2ddb457b5272d6c4b598564d8ac65059ef2c4` |
| `BUILD-RESULTS.json` | `03eb95513c6111804b59e6175892929bd4346be92c9b8942bed925442114cb7f` |
