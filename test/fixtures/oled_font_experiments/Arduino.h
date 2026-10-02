/* Minimal host-only Arduino surface for exercising the real OLED renderer. */
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#define PROGMEM
#define pgm_read_byte(address) (*reinterpret_cast<const uint8_t *>(address))

template <typename A, typename B>
inline auto min(A a, B b) -> decltype(a + b) { return a < b ? a : b; }
template <typename A, typename B>
inline auto max(A a, B b) -> decltype(a + b) { return a > b ? a : b; }

inline void yield() {}

class String {
  std::string value;
public:
  String(const char *text) : value(text ? text : "") {}
  const char *c_str() const { return value.c_str(); }
  unsigned int length() const { return static_cast<unsigned int>(value.size()); }
  void toCharArray(char *target, unsigned int capacity, unsigned int index = 0) const {
    if (!capacity) return;
    const size_t available = index < value.size() ? value.size() - index : 0;
    const size_t copied = std::min<size_t>(capacity - 1, available);
    std::memcpy(target, value.data() + std::min<size_t>(index, value.size()), copied);
    target[copied] = 0;
  }
};

class Print {
public:
  virtual ~Print() {}
  virtual size_t write(uint8_t byte) = 0;
};
