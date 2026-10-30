#pragma once
#include <cstddef>
#include <cstdint>

// A real byte CRC keeps changed and identical command streams distinct; no
// constant finalize() stub can conceal a missing frame or exhausted budget.
class CRC32 {
  uint32_t value = 0xffffffffU;
public:
  void reset() { value = 0xffffffffU; }
  template<class T> void update(T input) { update(&input, 1); }
  template<class T> void update(const T* input, size_t count) {
    const auto* bytes = reinterpret_cast<const uint8_t*>(input);
    for (size_t i = 0; i < count * sizeof(T); ++i) {
      value ^= bytes[i];
      for (unsigned bit = 0; bit < 8; ++bit)
        value = (value >> 1) ^ ((value & 1U) ? 0xedb88320U : 0U);
    }
  }
  uint32_t finalize() const { return value ^ 0xffffffffU; }
};
