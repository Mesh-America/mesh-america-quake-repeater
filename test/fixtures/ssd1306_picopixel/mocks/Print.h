#pragma once
#include <cstddef>
#include <cstdint>
class Print {
public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t) = 0;
  size_t print(const char* s) { size_t n=0; while (*s) n += write(*s++); return n; }
};
