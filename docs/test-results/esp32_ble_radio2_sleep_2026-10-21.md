<!-- meshcore-hosted-doc-link:start -->
<p class="meshcore-hosted-doc-link"><a href="https://mikecarper.github.io/MeshCore/test-results/esp32_ble_radio2_sleep_2026-10-21/">View this page on MeshCore Docs</a>.</p>
<!-- meshcore-hosted-doc-link:end -->

# ESP32 Bluetooth shutdown and radio2 CPU idle, 2026-10-21

The ESP32 changes cover two gaps identified while qualifying nRF52 CPU sleep:
reversibly stopping the Bluetooth host/controller, and allowing bounded MCU
light-sleep during a settled secondary-radio receive visit. This report
separates host/build coverage, SDK wait measurements and physical packet tests.

## Behavior and safeguards

Bluetooth off disconnects clients and completes host/controller teardown in
the main loop. Bluetooth on rebuilds the service without releasing controller
memory permanently or clearing successful bonds. Address, name, PIN and saved
stealth policy remain intact. Pending or failed teardown prevents CPU sleep.
The Bluedroid characteristics have deterministic TX/RX registration order;
heap fragmentation must not change a paired client's cached handles.

Companion, Repeater, Room Server and Sensor can idle during an eligible
radio2 visit. The decision requires a settled, validated receive profile,
working radio GPIO wake, no pending reception and physically stopped wireless
drivers. An absolute scanner deadline is checked again at sleep entry. The
sleep slice is at most 10 ms, ends at least 4 ms before the visit deadline and
requires at least 2 ms of useful time. Calibration, repair, ownership, queue,
network, USB and role deadlines retain their existing guards. The receiver
stays on. This does not enable sleep through an active Bluetooth/WiFi link.

## Host tests and builds

The scheduling, board wake, dispatcher and real role integration suites pass.
Coverage includes expired and wrapping deadlines, stale profile proofs,
pending interrupts, failed wake setup and SDK errors. The BLE adapter tests
exercise actual production code with ASan/UBSan, ownership differences,
partial initialization/teardown failures and repeated off/on cycles. Existing
nRF52 event/profile tests also pass; nRF52 hardware was not touched.

Full V4.3 FEM-off Companion, V3 Companion, V4 Repeater, Room and Sensor builds
pass their capability and memory gates. ESP32-C6 BLE (Arduino 3.1.3), the
NimBLE-Arduino V4 trial and RC32 Full (Arduino 3.3.11) also compile. RC32
exposed SDK service ownership and array-deletion defects; a version/hash-bound
build-local repair fixes those sources without editing a shared SDK install.

Classic Heltec V2 BLE remains below its required 8,192-byte internal RAM
reserve. The baseline has 2,552 bytes free and the candidate has 2,432 bytes
free, a 120-byte regression against an existing failure. Removing an
unnecessary WiFi-driver reference recovered 1,208 bytes. The gate was retained;
this target is not reported as passing.

## Physical V4 observations

The test board is a Heltec V4.3 OLED using its matching FEM-off Full Companion
image. The first candidate reports source suffix `278c9ffb`; its published
equivalent after history cleanup is `61eecbd97`. An application-only write and
complete readback preserved the partition table, OTA metadata, identity,
settings and credential digests. No whole-flash backup, bootloader write or
other-device update was performed.

With Bluetooth/WiFi off and power saving on, only this V4's USB data was
suspended. After the host-loss grace period, a 90-second diagnostic window
recorded **4,635 SDK light-sleep calls and returns**, zero SDK errors, zero
short waits, zero vetoes and zero pending-wake returns. Cumulative call time
was 35.523299 seconds; the longest call was 9,869 microseconds. The mixed
profiles were 910.525 MHz / BW62.5 / SF7 / CR5 and 916 MHz / BW125 / SF9 / CR5.
USB authorization and runtime policy were restored. Core errors remained zero.
These are SDK wait measurements, not electrical current or residency readings.

Two initial saved-bond Bluetooth off/on sessions passed. Further testing
exposed both a host-side notification-acquisition problem and a real firmware
GATT-handle ordering defect. The host driver now uses ordinary StartNotify.
The original failures are retained; clearing a client cache is not accepted
as proof that firmware handles remain stable or an existing cache migrates.

Encrypted nonce tests on both frequencies have not yet passed. Earlier
six-packet attempts completed physical transmissions but did not deliver all
expected nonces. An awake control then stopped before transmitting when the
peer rejected a TX-power setting. These failures remain separate from the
successful SDK wait window; that window does not qualify end-to-end radio2
delivery. The peer is an ESP32 XIAO S3 WIO, independently identified over USB.

Private artifacts, receipts and traces are retained under
`/home/mesh/hwtest/esp32-ble-radio2-sleep-cd4ea053-20261021/`.
See [power-saving diagnostics](../power_saving_diagnostics.md) for the controls
and the limits of interpreting wait counters as energy savings.
