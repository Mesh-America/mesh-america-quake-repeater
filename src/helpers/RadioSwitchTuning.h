#pragma once
#include <stdint.h>

namespace mesh {

// Saved policy for one physical radio, shared by both RF profiles. SPI MHz 0
// retains the board's default clock (which need not be an integer MHz).
struct RadioSwitchTuning {
  enum Feature : uint8_t {
    Warm = 1, Fs = 2, Packet = 4, Iq = 8, Modem = 16,
    Batch = 32, Buffer = 64
  };
  uint8_t flags = 0;
  uint8_t spi_mhz = 0;
  bool operator==(const RadioSwitchTuning& other) const {
    return flags == other.flags && spi_mhz == other.spi_mhz;
  }
  bool operator!=(const RadioSwitchTuning& other) const { return !(*this == other); }
};

struct RadioSwitchCapabilities {
  uint8_t flags = 0;
  // Bit N permits 2^N MHz; bit 0 (1 MHz) is deliberately unused.
  uint8_t spi_clocks = 0;
};

inline bool validRadioSwitchTuning(const RadioSwitchTuning& value,
                                  const RadioSwitchCapabilities& caps) {
  if (value.flags & ~caps.flags) return false;
  if (!value.spi_mhz) return true;
  for (uint8_t n = 1; n <= 4; ++n)
    if (value.spi_mhz == (1U << n)) return caps.spi_clocks & (1U << n);
  return false;
}

}  // namespace mesh
