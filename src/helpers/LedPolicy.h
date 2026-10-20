#pragma once

#include <atomic>

namespace mesh { namespace leds {

inline std::atomic<bool>& policy() {
  static std::atomic<bool> value{true};
  return value;
}

inline bool enabled() { return policy().load(std::memory_order_relaxed); }
inline void setEnabled(bool value) { policy().store(value, std::memory_order_relaxed); }
void applyStatusPolicy();

}} // namespace mesh::leds
