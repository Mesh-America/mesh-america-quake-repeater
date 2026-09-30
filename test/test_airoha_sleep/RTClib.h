#pragma once

#include <stdint.h>

// Command/ACK tests do not use RTC conversion. Keep the provider header
// compilable without the hardware I2C dependencies of the Arduino RTC library.
class DateTime {
public:
  DateTime(uint16_t, uint8_t, uint8_t, uint8_t, uint8_t, uint8_t) {}
  uint32_t unixtime() const { return 0; }
};
