#pragma once

#ifndef MESH_HIL_SPI_STARTUP_DIAG
#define MESH_HIL_SPI_STARTUP_DIAG 0
#endif
#if MESH_HIL_SPI_STARTUP_DIAG != 0 && MESH_HIL_SPI_STARTUP_DIAG != 1
#error "SPI startup diagnostic flag must be 0 or 1"
#endif

#if MESH_HIL_SPI_STARTUP_DIAG
#if !defined(NRF52_PLATFORM)
#error "SPI startup diagnostic requires nRF52"
#endif

#include "Nrf52BufferedRadioHal.h"
#include <helpers/nrf52/SoftDeviceState.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace mesh { namespace spistartup {

enum Phase : uint32_t { Idle = 0, Query = 1, Transfer = 2, Completed = 3, Refused = 4 };

// Fixed 14-word ABI for private SWD reads, including before USB is usable.
// Each word is independently observable; this is not an atomic snapshot.
struct Capture {
  uint32_t magic, version, size_bytes, phase;
  uint32_t queries, first_query_result, first_query_enabled;
  uint32_t last_query_result, last_query_enabled;
  uint32_t begun, completed, refused, last_opcode, last_length;
};
static_assert(sizeof(Capture) == 56 && offsetof(Capture, begun) == 36
              && offsetof(Capture, last_length) == 52, "SPI startup capture ABI changed");
extern "C" {
extern volatile Capture mesh_hil_spi_startup;
}

} } // namespace mesh::spistartup

// Diagnostic only: the global nrfx anomaly-198 workaround cannot coexist
// with SoftDevice. Refuse the actual frame unless its disabled state was
// positively established by the existing LTO-safe supervisor query.
class NrfRadioSpiStartupDiagHal : public Nrf52BufferedRadioHal {
public:
  explicit NrfRadioSpiStartupDiagHal(SPIClass& bus, uint32_t hz)
      : Nrf52BufferedRadioHal(bus, hz) {}

  void spiTransfer(uint8_t* out, size_t len, uint8_t* in) override {
    if (!len) return;
    auto& capture = mesh::spistartup::mesh_hil_spi_startup;
    capture.last_opcode = out ? out[0] : UINT32_MAX;
    capture.last_length = static_cast<uint32_t>(len);
    capture.phase = mesh::spistartup::Query;
    uint8_t enabled = 0;
    const uint32_t result = mesh_nrf52::softdeviceIsEnabled(enabled);
    if (!capture.queries) {
      capture.first_query_result = result;
      capture.first_query_enabled = enabled;
    }
    ++capture.queries;
    capture.last_query_result = result;
    capture.last_query_enabled = enabled;
    if (result != 0 || enabled != 0) {
      if (in) memset(in, 0x2a, len); // SX126x command-failed status.
      ++capture.refused;
      capture.phase = mesh::spistartup::Refused;
      return;
    }
    ++capture.begun;
    capture.phase = mesh::spistartup::Transfer;
    Nrf52BufferedRadioHal::spiTransfer(out, len, in);
    ++capture.completed;
    capture.phase = mesh::spistartup::Completed;
  }
};
#endif
