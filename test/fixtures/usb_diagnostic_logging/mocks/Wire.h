#pragma once

#include <Arduino.h>
#include <array>

class TwoWire {
 public:
  bool present = true;
  bool all_addresses_present = false;
  unsigned probes = 0;
  unsigned fail_probe_count = 0;
  std::array<uint8_t, 5> frame{{0, 1, 2, 3, 4}};
  uint8_t reply_length = 5;
  uint8_t current_address = 0;
  unsigned cursor = 0;
  void beginTransmission(uint8_t address) { current_address = address; ++probes; }
  uint8_t endTransmission() const {
    if (probes <= fail_probe_count) return 2;
    return (all_addresses_present || (present && current_address == 0x2E)) ? 0 : 2;
  }
  uint8_t requestFrom(uint8_t, uint8_t) { cursor = 0; return reply_length; }
  int available() const { return static_cast<int>(reply_length) - static_cast<int>(cursor); }
  int read() { return cursor < reply_length ? frame[cursor++] : -1; }
};

extern TwoWire Wire;
