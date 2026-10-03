#pragma once
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "../../../mocks/Arduino.h"
#pragma GCC diagnostic pop
#include <cassert>

uint32_t tud_cdc_n_write_available(uint8_t instance);
class MockSerial : public Stream {
 public:
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  int availableForWrite() override { return tud_cdc_n_write_available(0); }
  size_t write(const uint8_t*, size_t) override {
    assert(false && "native nRF52 console must not use retrying Serial.write");
    return 0;
  }
  void flush() override { assert(false && "console must not forward Serial.flush"); }
};
extern MockSerial Serial;
