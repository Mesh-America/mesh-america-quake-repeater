#pragma once

#include "FirmwareInfo.h"

// Device-side accessor for the running firmware's own image (to read its EndF trailer).
// ESP32 reads the running A/B app partition; nRF52 reads its memory-mapped app
// region. The portable scan logic in FirmwareInfo.{h,cpp} is host-testable.

namespace mesh {
namespace ota {

// Locate this firmware's EndF trailer in its own flash image. Returns false if unsupported on this
// platform or no valid EndF is present (e.g. firmware built without the EndF build hook).
// ESP32 caches successful metadata for this boot while the running partition address/size match;
// missing partitions, changed geometry and read failures are never cached. OTA writes inactive flash.
bool ota_self_firmware(SelfFwInfo& out);

// Read `len` bytes of the running firmware image at offset `off` (ESP32: running partition via
// esp_partition_read; nRF52: memory-mapped app region). false on unsupported platforms.
bool ota_self_read(uint32_t off, uint8_t* buf, uint32_t len);

// Compute (once) + cache our running firmware's manifest + merkle leaves in `c`, then serve it from
// flash as a full `.mota` (payload read on demand per block; only metadata held in RAM). Returns false
// if no EndF / image too big / OOM. Device platforms only.
struct OtaContext;
bool ota_serve_self(OtaContext& c, uint32_t fw_version);   // target = this node's own (c.manager.target())

} // namespace ota
} // namespace mesh
