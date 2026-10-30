<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/heltec_v2_ble_memory_2026-10-22/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# Heltec V2 BLE RAM reserve repair, 22 October 2026

Status: **build, memory and host tests PASS**. Physical V2 operation was not
tested in this work. The earlier RAM failure remains recorded below.

Clean source
[`1d4016f48`](https://github.com/mikecarper/MeshCore/commit/1d4016f483caaddebde4c923f7eea3dee27ac3ea)
was built through the canonical builder as `Heltec_v2_companion_radio_ble`,
using the auto feature profile, Cascade runtime defaults, USA Cascadia radio
preset and release-length version `v1.18.0.1-halo-keymind-cascade-dev-1d4016f4`.
The [safe receipt](heltec_v2_ble_memory_2026-10-22.safe.json) binds the source,
linked measurements and packaged artifact hashes.

## Change and retained behavior

Only V2 BLE explicitly enables the existing `MESH_CONTACT_CACHE` policy.
Its `Heltec_v2_companion_radio_ble_ps` alias inherits the same setting.
Other V2 profiles and the default cache policies of other boards are unchanged.

All 160 contacts, eight channels and 128 offline frames remain available.
The cache keeps 16 paths and 16 shared secrets resident, rather than embedding
a complete path and shared secret in every contact object. Other paths remain
accessible through checked reads of existing contact records; cold ESP32
secrets are recalculated without secret-file I/O. These resident-cache limits
do not reduce the contact capacity. Cold access can add filesystem reads or
key-calculation work.

The Bluedroid Bluetooth host, PIN authentication, bond storage, dependencies,
radio/display setup, contact protocol and 152-byte contact-file records remain
unchanged. No pairing migration or repartitioning is introduced. The packaged
capability verification passes with an empty reductions list.

The existing 8,192-byte static DRAM reserve remains mandatory. The runtime
model additionally reserves 6,144 bytes for this explicit ESP32 cache opt-in:
4,096 bytes for retained reader buffering plus 2,048 bytes for reader objects,
allocator metadata and related overhead. This is above the unchanged common
filesystem and transient allowances; it is not a claim of zero heap cost.
Automatic Full profiles keep their existing accounting policy.

## Linked results

| Check | Baseline `76437c6bf` | Fixed `1d4016f48` |
| --- | ---: | ---: |
| Static DRAM region | 124,580 bytes | 124,580 bytes |
| Occupied static span | 122,964 bytes | 112,140 bytes |
| Static DRAM free | 1,616 bytes | 12,440 bytes |
| Required static reserve | 8,192 bytes | 8,192 bytes |
| Margin above reserve | -6,576 bytes, FAIL | 4,248 bytes, PASS |

The fixed image saves **10,824 static bytes**. Its runtime model passes with
181,400 internal bytes available versus 141,104 required, including the extra
reader allowance. The modeled margin is 40,296 bytes; these are linked
capacity estimates, not running free-heap or fragmentation measurements.

The application occupies 1,810,568 of 3,342,336 app-slot bytes. The partition
table is byte-identical to the baseline. Both firmware and merged packages,
capability verification and unchanged application-size gates pass. The failed
baseline ELF/map and successful candidate/final artifacts are retained privately.

## Verification and limits

All 74 host test methods passed:

- 14 contact-cache methods, including the exact non-Full ESP32 160-contact
  configuration with default secret-flash caching disabled. Sanitized cases
  cover eviction, unchanged frames/files, full reload, cooperative saves,
  held snapshots, failed-write rollback and cold-secret recalculation.
- 53 RAM-policy methods, including the resolved-environment metadata check.
  Synthetic ELF checks reject the old capacity and one byte below the new
  requirement, and accept the exact new boundary.
- Seven contact-lifetime, partial-record and packet-streaming methods.

The unit workflow now builds this exact classic ESP32 target at release-version
length and enforces both memory gates. The inherited power-saving alias is
checked by the recipe contract; an identical feature configuration was not
built a second time. No firmware feature or capacity was removed to obtain
the pass, and no memory gate was lowered.

No radio was flashed or contacted. Physical V2 boot, pairing/reconnect,
populated contact sync, filesystem latency and sleep remain outside this
build/host result. It closes the documented V2 RAM build failure, not those
hardware qualification claims.
