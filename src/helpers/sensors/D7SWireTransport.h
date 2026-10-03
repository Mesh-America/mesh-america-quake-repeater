#pragma once

#include <Wire.h>
#include "D7S.h"

namespace d7s {

// D7S register access over an Arduino TwoWire-compatible bus (templated so tests can use a fake). Register addresses are 16-bit, sent MSB first;
// reads use a repeated start (endTransmission(false)) between the address and the data phase.
// Returns false on a NACK or a short read. Wire is not bounded by a timeout on every core, so a
// bus that is held low can stall the caller; see docs/d7s-integration.md.
template <class Bus>
class BasicWireTransport : public Transport {
public:
  void begin(Bus* bus, uint8_t deviceAddress = Sensor::Address) {
    wire = bus;
    address = deviceAddress;
  }

  bool read(uint16_t reg, uint8_t* data, size_t size) override {
    if (!wire || !data || size == 0 || size > MaxRead) return false;
    wire->beginTransmission(address);
    wire->write(static_cast<uint8_t>(reg >> 8));
    wire->write(static_cast<uint8_t>(reg));
    if (wire->endTransmission(false) != 0) return false;
    if (wire->requestFrom(address, static_cast<size_t>(size)) != size) return false;
    for (size_t i = 0; i < size; ++i) {
      if (!wire->available()) return false;
      data[i] = static_cast<uint8_t>(wire->read());
    }
    return true;
  }

  bool write(uint16_t reg, uint8_t value) override {
    if (!wire) return false;
    wire->beginTransmission(address);
    wire->write(static_cast<uint8_t>(reg >> 8));
    wire->write(static_cast<uint8_t>(reg));
    wire->write(value);
    return wire->endTransmission(true) == 0;
  }

private:
  static constexpr size_t MaxRead = 32;  // Conservative cap: the AVR buffer is 32, the nRF52 core's is 64.
  Bus* wire = nullptr;
  uint8_t address = Sensor::Address;
};

// The firmware uses the Arduino bus; host tests substitute a fake bus type.
using WireTransport = BasicWireTransport<TwoWire>;

}  // namespace d7s
