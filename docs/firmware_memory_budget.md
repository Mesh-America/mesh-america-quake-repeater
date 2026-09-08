# Firmware memory checks

Every firmware environment runs `scripts/check_firmware_ram.py` against its
linked ELF before producing or uploading an image. `build.sh`, including
option 3, also requires a passing report before collecting release files.
Native host tests do not use a microcontroller RAM budget.

The check reserves room for enabled runtime allocations as well as static
data. A firmware image fitting its board's reported RAM total is insufficient:
the display, packet pool, USB, Bluetooth workers and WiFi can allocate after
startup. The T096 Full 1.17.1.5 report exposed this distinction.

## What is counted

| Platform | Source of available runtime RAM |
| --- | --- |
| nRF52 | Actual `__HeapBase` and `__HeapLimit`; excludes SoftDevice, retained state, ISR stack and the dedicated 64 KiB mOTA arena where present |
| ESP32, S3, C3, C6 | Linked ESP-IDF memory-region, capability and reservation tables; only internal, byte-addressable heap counts |
| RP2040/RP2350 | `__end__` to `__HeapLimit`, according to the selected linker |
| STM32 | `_end` to `_estack`, minus `_Min_Stack_Size` |

ESP32 PSRAM, instruction-only RAM and RTC RAM never increase the internal
budget. On chips other than classic ESP32, the late-reclaimed ROM stack region
is excluded because its silicon-specific reservations are only known at boot.
Classic ESP32 additionally retains its existing 8 KiB **static DRAM** check.

The policy adds allowances for task stacks, radio packet pools, screen objects
and pixel buffers, filesystem/sensor allocations, enabled wireless stacks,
MQTT connections, OTA scratch and transient allocations. A 160x80 ST7735
framebuffer needs 25,602 bytes; an OLED allowance is 4 KiB. nRF52 Full with that
color framebuffer must have at least 72 KiB available before startup allocations.
Headless and OLED devices use their own smaller totals. The JSON lists each
component and checks the largest available region against the largest planned
single allocation.

These are engineering allowances for supported configurations, not measured
free heap after boot or a guarantee against every future allocation failure.
Unknown platforms, unknown display drivers and missing linker metadata fail
closed. `MESH_MIN_RUNTIME_HEAP` can raise a profile's requirement; it cannot
lower the calculated requirement. Add an allocation allowance when adding a
display, transport or other substantial feature.

## Release evidence and regression tests

Each newly built firmware has a matching `.memory.json` report. It records
the linked ELF SHA-256, available internal RAM, required RAM, largest region,
and SHA-256 hashes for the actual firmware files and capability manifest.
Packaging and resumed builds reject absent reports, failures, stale ELFs,
missing files and changed firmware. Do not reuse a report for another build.

Run PlatformIO commands sequentially in this checkout:

```sh
python3 -B test/test_firmware_ram.py
python3 -B test/test_t096_full_memory.py
python3 -B test/test_nrf52_ble_startup.py
python3 -B test/test_shared_mota_queue.py
python3 -B test/test_cascade_release_package.py
pio test -e native -f test_ota
```

Tests cover all resolved firmware environments' hooks, real ELF parsing,
allocator table formats, excluded memory, allocation failure, package/report
binding and the published T096 failing budget. Shared mOTA tests exercise
complete transfers, queue wraparound, unread-message order, source ownership,
stop/disconnect and repeated reuse. Bluetooth tests inject task and service
startup failures. The manual staging buffer also has allocation-failure and
repeated release tests.

For older releases without saved ELFs, an audit can compare their ESP allocator
tables against a matching pinned SDK ELF and read reservations from the
**published application itself** using `scripts/audit_esp32_image_ram.py`.
Unrecognized layouts require another matching reference or a historical rebuild.
An audit must identify original-log/linker calculations separately from new
ELF checks and verify the published firmware hashes.

Physical validation remains necessary: boot with and without USB, pair and
exchange Bluetooth messages, visit every screen, wake with the button, enable
logging/MQTT, transfer mOTA, and monitor heap during a sustained workload.
See [memory monitoring](https://github.com/mikecarper/MeshCore/blob/keymindCascade/MEMORY_MONITORING.md)
for runtime diagnostics.
