#pragma once

#include <stdint.h>

struct TwoWire {
  uint8_t result = 0, address = 0;
  unsigned probes = 0;
  void beginTransmission(uint8_t value) { address = value; }
  uint8_t endTransmission() { ++probes; return result; }
};
inline TwoWire Wire;
