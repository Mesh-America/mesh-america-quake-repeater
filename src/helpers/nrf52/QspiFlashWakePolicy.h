#pragma once

#include <stdint.h>

namespace mesh {
namespace nrf52 {

// Supported NOR parts need up to 45 us after release from deep power-down.
static const uint32_t QSPI_DPD_WAKE_GUARD_US = 50u;
static const uint8_t QSPI_RELEASE_FROM_DPD_OPCODE = 0xABu;

inline bool qspiReleaseFromDeepPowerDownBit(uint8_t bit_index) {
  return bit_index < 8u &&
      ((QSPI_RELEASE_FROM_DPD_OPCODE >> (7u - bit_index)) & 1u) != 0;
}

} // namespace nrf52
} // namespace mesh
