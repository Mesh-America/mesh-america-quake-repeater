#pragma once

#if defined(OTA_TOWER_AUTO_STORE)
#if !defined(NRF52_PLATFORM) || !defined(HELTEC_TOWER_V2_SDCARD) || \
    !defined(OTA_SD_STORE) || !defined(OTA_FLASH_STORE)
#error "MeshTower automatic OTA storage requires the qualified nRF52 SD primary"
#endif

#include "OtaBlInfo.h"
#include "OtaStoreFlashNrf52.h"
#include "OtaStoreSdNrf52.h"
#include "MotaContainer.h"
#include <new>

namespace mesh {
namespace ota {

// Keep the SD volume object stable because the archive shares its mounted
// filesystem. Internal construction is deferred: its constructor invalidates
// the same retained authorization bytes used by the SD application handoff.
// Selecting media never opens/removes a staging file, and an operation failure
// never redirects an already selected transfer to a different medium.
class OtaStoreTowerNrf52 : public OtaStore {
  enum Mode : uint8_t { UNSELECTED, SD_MODE, INTERNAL_MODE, UNAVAILABLE };
  OtaStoreSdNrf52 _sd;
  alignas(OtaStoreFlashNrf52) uint8_t _internal_bytes[sizeof(OtaStoreFlashNrf52)];
  OtaStoreFlashNrf52* _internal = nullptr;
  Mode _mode = UNSELECTED;
  bool _compatible = false;
  bool _has_stage = false;
  bool _layout_rejected = false;
  bool _layout_accepted = false;
  const char* _reason = "not selected";
  const char* _error = nullptr;

  OtaStore* active() {
    return _mode == SD_MODE ? static_cast<OtaStore*>(&_sd) :
           _mode == INTERNAL_MODE ? _internal : nullptr;
  }
  const OtaStore* active() const {
    return _mode == SD_MODE ? static_cast<const OtaStore*>(&_sd) :
           _mode == INTERNAL_MODE ? _internal : nullptr;
  }
  bool resumeMatches(const uint8_t* mid, uint32_t target) {
    uint8_t raw[MOTA_MFL];
    MotaManifest manifest;
    const OtaStore* s = active();
    if (!s || !s->read(8u, raw, sizeof(raw)) ||
        !mota_parse_manifest(raw, sizeof(raw), manifest)) {
      _error = "staged manifest is invalid";
      return false;
    }
    if ((mid && memcmp(manifest.merkle_root, mid, 4u) != 0) ||
        (target != 0u && manifest.target_id != target)) {
      _error = "staged MID/target does not match";
      return false;
    }
    if (_mode == INTERNAL_MODE && (manifest.is_full() || manifest.is_bootloader())) {
      _error = "internal fallback accepts application deltas only";
      return false;
    }
    return true;
  }

public:
  OtaStoreTowerNrf52() = default;
  OtaStoreTowerNrf52(const OtaStoreTowerNrf52&) = delete;
  OtaStoreTowerNrf52& operator=(const OtaStoreTowerNrf52&) = delete;
  ~OtaStoreTowerNrf52() override {
    if (_internal) _internal->~OtaStoreFlashNrf52();
  }

  // Call from the deferred OTA preparation path, after normal board startup.
  // Getter/status calls deliberately cannot turn USB startup into an SD probe.
  bool selectStorage() {
    if (_mode != UNSELECTED) return _compatible;
    const bool sd_ready = _sd.probeMedia();
    const OtaBlCaps caps = ota_bootloader_app_caps();
    const bool sd_profile = caps.present && (caps.storage_flags & OTA_BL_STORAGE_SD) != 0u;
    if (sd_ready) {
      _mode = SD_MODE;
      _compatible = sd_profile;
      _reason = sd_profile ? "SD staging" : "SD present; incompatible OTAFIX bootloader";
    } else if (sd_profile && caps.optional_app_storage == OTA_BL_STORAGE_STAGE_CEILING) {
      _internal = new (_internal_bytes) OtaStoreFlashNrf52();
      _mode = INTERNAL_MODE;
      _compatible = true;
      _reason = "SD unavailable; internal delta staging";
    } else {
      _mode = UNAVAILABLE;
      _reason = "SD unavailable; OTAFIX lacks qualified internal fallback";
    }
    return _compatible;
  }
  // The caller must finish/cancel the transfer first. Do not discard durable
  // staged bytes here: a following reopen may intentionally resume them.
  void resetSelection() {
    if (_internal) {
      _internal->~OtaStoreFlashNrf52();
      _internal = nullptr;
    }
    _mode = UNSELECTED;
    _compatible = false;
    _has_stage = false;
    _layout_rejected = false;
    _layout_accepted = false;
    _reason = "not selected";
    _error = nullptr;
  }
  bool usesExternalStore() const { return _mode == SD_MODE; }
  bool usesExternal() const { return usesExternalStore(); }
  bool usesInternal() const { return _mode == INTERNAL_MODE; }
  bool compatible() const { return _compatible; }
  const char* selectionReason() const { return _reason; }
  OtaStoreSdNrf52& sdStore() { return _sd; }
  OtaStoreSdNrf52& externalStore() { return _sd; }
  // Only use after usesInternal() succeeds. This accessor must not construct
  // an internal store while an SD authorization is being prepared/published.
  OtaStoreFlashNrf52& internalStore() { return *_internal; }
  const char* last_error() const {
    if (_error) return _error;
    return _mode == SD_MODE ? _sd.last_error() : _reason;
  }

  bool begin(uint32_t n) override {
    _has_stage = false;
    if (!selectStorage() || _layout_rejected) return false;
    if (_mode == INTERNAL_MODE && !_layout_accepted) {
      _error = "internal fallback requires a planned application delta";
      return false;
    }
    _error = nullptr;
    _has_stage = active()->begin(n);
    if (!_has_stage && _mode == INTERNAL_MODE) _error = "internal OTA begin failed";
    return _has_stage;
  }
  bool write(uint32_t p, const uint8_t* d, uint32_t n) override {
    return _has_stage && active()->write(p, d, n);
  }
  bool read(uint32_t p, uint8_t* d, uint32_t n) const override {
    return _has_stage && active()->read(p, d, n);
  }
  uint32_t capacity() const override {
    const OtaStore* s = active();
    return _compatible && s ? s->capacity() : 0u;
  }
  uint32_t staged_size() const override {
    return _has_stage ? active()->staged_size() : 0u;
  }
  void clear() override {
    OtaStore* s = active();
    if (s) s->clear();
    _has_stage = false;
    _layout_rejected = false;
    _layout_accepted = false;
    _error = nullptr;
  }
  bool discard() override {
    if (!selectStorage()) return false;
    const bool ok = active()->discard();
    _has_stage = false;
    _layout_rejected = false;
    _layout_accepted = false;
    if (!ok && _mode == INTERNAL_MODE) _error = "internal OTA discard failed";
    return ok;
  }
  bool set_meta_size(uint32_t n) override {
    return _has_stage && active()->set_meta_size(n);
  }
  bool finalize() override { return _has_stage && active()->finalize(); }
  void checkpoint() override { if (_has_stage) active()->checkpoint(); }
  bool reopen() override { return reopenFor(nullptr, 0u); }
  bool reopenFor(const uint8_t* mid, uint32_t target) override {
    _has_stage = false;
    _layout_rejected = false;
    _layout_accepted = false;
    _error = nullptr;
    if (!selectStorage()) return false;
    OtaStore* s = active();
    const bool reopened = _mode == SD_MODE ? _sd.reopen() : s->reopenFor(mid, target);
    // Rejecting a mismatched SD container must not call SD clear(): that
    // method durably deletes the very file a later explicit pull may need.
    _has_stage = reopened && resumeMatches(mid, target);
    return _has_stage;
  }
  bool plan_layout(bool full, uint32_t image, uint32_t offset,
                   uint32_t payload, bool bootloader) override {
    _layout_rejected = true;
    _layout_accepted = false;
    _error = nullptr;
    if (!selectStorage()) return false;
    if (_mode == INTERNAL_MODE && (full || bootloader)) {
      _error = "internal fallback accepts application deltas only";
      return false;
    }
    _layout_rejected = !active()->plan_layout(full, image, offset, payload, bootloader);
    _layout_accepted = !_layout_rejected;
    return !_layout_rejected;
  }

  // Management always addresses the physical SD card. These operations never
  // switch a selected application transfer between SD and internal storage.
  bool formatCard(MainBoard& board) { return _sd.formatCard(board); }
  bool eraseCard(MainBoard& board) { return _sd.eraseCard(board); }
  bool getSpace(MainBoard& board, uint64_t& used, uint64_t& free) {
    return _sd.getSpace(board, used, free);
  }
  bool listFiles(MainBoard& board, uint16_t page, char* reply, size_t cap) {
    return _sd.listFiles(board, page, reply, cap);
  }
};

} // namespace ota
} // namespace mesh

#endif
