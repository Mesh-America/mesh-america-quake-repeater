#pragma once

#include <stddef.h>
#include <stdint.h>

#if !defined(MESH_MORSE_HIL_RAW_RSSI) || MESH_MORSE_HIL_RAW_RSSI != 1 \
    || !defined(ESP32_PLATFORM) || !defined(MESH_MORSE_HIL) || !MESH_MORSE_HIL \
    || !defined(MESH_MORSE_HIL_PRODUCTION_RF) || !MESH_MORSE_HIL_PRODUCTION_RF
#error "Raw Morse RSSI requires ESP32 production-equivalent HIL diagnostics"
#endif

#ifndef MESH_MORSE_HIL_RAW_WINDOW_MS
#define MESH_MORSE_HIL_RAW_WINDOW_MS 60000
#endif

namespace mesh {

struct MorseRawRssiTraceEntry {
  uint32_t millis;
  float rssi_dbm;
  uint8_t flags;
};

// Explicit ESP32 diagnostic only. Retain every half-dBm measurement from RX
// entry, including arming and candidates. Freeze the prefix on overflow; never
// overwrite its initial detector history or stream while the radio samples.
class MorseRawRssiTrace {
public:
  static constexpr uint32_t WindowMillis = MESH_MORSE_HIL_RAW_WINDOW_MS;
  static_assert(WindowMillis >= 30000 && WindowMillis <= 60000,
                "Raw Morse trace window must be 30000..60000 milliseconds");
  static constexpr size_t Capacity = WindowMillis / 2 + 1;
  enum StopReason : uint8_t { None, Window, Full, Gap, Value };
  void clear() { _length = _total = _last_elapsed = 0; _reason = None; }
  size_t length() const { return _length; }
  uint32_t total() const { return _total; }
  bool truncated() const { return _reason != None; }
  StopReason stopReason() const { return _reason; }
  bool read(size_t offset, MorseRawRssiTraceEntry& out) const {
    if (offset >= _length) return false;
    const size_t anchor = offset / AnchorStride;
    uint32_t elapsed = _anchors[anchor];
    for (size_t index = anchor * AnchorStride + 1; index <= offset; ++index)
      elapsed += delta(_entries[index]);
    out = {elapsed, -0.5f * _entries[offset].raw_rssi, 0};
    return true;
  }
  void sample(float rssi, uint32_t elapsed, uint8_t flags) {
    (void)flags;
    ++_total;
    if (_reason != None) return;
    if (elapsed > WindowMillis) { _reason = Window; return; }
    if (_length == Capacity) { _reason = Full; return; }
    const uint32_t dt = _length ? elapsed - _last_elapsed : 0;
    if (dt > UINT16_MAX) { _reason = Gap; return; }
    // SX126x GetRssiInst is exactly -0.5 * one unsigned byte. Reject an
    // unrepresentable value instead of silently rounding a different backend.
    if (!(rssi >= -127.5f && rssi <= 0.0f)) { _reason = Value; return; }
    const float raw = -2.0f * rssi;
    if (raw != static_cast<uint16_t>(raw)) { _reason = Value; return; }
    if (_length % AnchorStride == 0) _anchors[_length / AnchorStride] = elapsed;
    _entries[_length++] = {uint8_t(dt), uint8_t(dt >> 8), uint8_t(raw)};
    _last_elapsed = elapsed;
  }
private:
  static constexpr size_t AnchorStride = 256;
  struct StoredEntry { uint8_t delta_low, delta_high, raw_rssi; };
  static_assert(sizeof(StoredEntry) == 3, "Raw Morse entries must remain three bytes");
  static uint16_t delta(const StoredEntry& entry) {
    return uint16_t(entry.delta_low) | uint16_t(uint16_t(entry.delta_high) << 8);
  }
  StoredEntry _entries[Capacity];
  uint32_t _anchors[(Capacity + AnchorStride - 1) / AnchorStride];
  uint32_t _length = 0, _total = 0, _last_elapsed = 0;
  StopReason _reason = None;
};

} // namespace mesh
