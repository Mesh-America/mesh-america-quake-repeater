#pragma once

#ifndef COMPANION_MESH_PSRAM_STORAGE
#define COMPANION_MESH_PSRAM_STORAGE 0
#endif
#if COMPANION_MESH_PSRAM_STORAGE != 0 && COMPANION_MESH_PSRAM_STORAGE != 1
#error "COMPANION_MESH_PSRAM_STORAGE must be 0 or 1"
#endif

#if COMPANION_MESH_PSRAM_STORAGE
#if !defined(ESP32_PLATFORM) || !defined(BOARD_HAS_PSRAM) \
    || !defined(COMPANION_RADIO_FULL) || !defined(INDICATOR_TRANSPORT_RENDER_PROFILE) \
    || !defined(MESH_PRIMARY_ESPNOW) || !MESH_PRIMARY_ESPNOW
#error "Late PSRAM mesh storage requires the qualified Indicator ESP-NOW Full recipe"
#endif
#if defined(OTA_SHARED_COMPANION_QUEUE)
#error "Late PSRAM mesh storage retains the independent full-capacity queue"
#endif
#include <sdkconfig.h>
#if !defined(CONFIG_IDF_TARGET_ESP32S3) || !CONFIG_SPIRAM
#error "Late PSRAM mesh storage requires configured ESP32-S3 PSRAM"
#endif
#include <esp_heap_caps.h>
#include <esp32-hal-psram.h>
#include <new>
#include <stddef.h>
#include <stdlib.h>
#include <utility>

namespace mesh {

// This object owns only a pointer during global construction. setup() calls
// begin() explicitly once the board/Arduino PSRAM initialization has finished.
// get() never performs hidden allocation or permits access before that point.
template<typename T> class CompanionPsramMesh {
  T* value_ = nullptr;
  bool constructing_ = false;
public:
  enum class Result { Ready, MissingPsram, AllocationFailed };
  CompanionPsramMesh() = default;
  ~CompanionPsramMesh() {
    if (value_) {
      value_->~T();
      heap_caps_free(value_);
    }
  }
  CompanionPsramMesh(const CompanionPsramMesh&) = delete;
  CompanionPsramMesh& operator=(const CompanionPsramMesh&) = delete;
  CompanionPsramMesh(CompanionPsramMesh&&) = delete;
  CompanionPsramMesh& operator=(CompanionPsramMesh&&) = delete;

  template<typename... Args> Result begin(Args&&... args) {
    if (constructing_) abort();
    if (value_) return Result::Ready;
    if (!psramFound()) return Result::MissingPsram;
    // Match the old global object's zero initialization before invoking its
    // constructor. Several mesh members intentionally rely on that state.
    void* storage = heap_caps_calloc(1, sizeof(T), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!storage) return Result::AllocationFailed;
    constructing_ = true;
    T* constructed = new (storage) T(std::forward<Args>(args)...);
    value_ = constructed;
    constructing_ = false;
    return Result::Ready;
  }
  T& get() const {
    // NDEBUG must not turn a bad startup order into a null/partial mesh.
    if (constructing_ || !value_) abort();
    return *value_;
  }
};

} // namespace mesh
#endif
