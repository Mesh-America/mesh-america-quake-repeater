#pragma once
#include <cstddef>
#include <cstdint>

// Print/Arduino defines these before ordinary firmware headers. Keep them in
// the host build too: a local variable named HEX would otherwise compile here
// yet be expanded to an invalid numeric token on the actual board.
#define HEX 16
#define DEC 10
#define OCT 8
#define BIN 2

uint32_t millis();

class Stream {
public:
  virtual ~Stream() = default;
  virtual int available() = 0;
  virtual int read() = 0;
  virtual size_t write(const uint8_t*, size_t) = 0;
  virtual int availableForWrite() { return 4096; }
};
