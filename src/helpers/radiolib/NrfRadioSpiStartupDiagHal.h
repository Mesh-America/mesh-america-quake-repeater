#pragma once

#ifndef MESH_HIL_SPI_STARTUP_DIAG
#define MESH_HIL_SPI_STARTUP_DIAG 0
#endif
#if MESH_HIL_SPI_STARTUP_DIAG != 0 && MESH_HIL_SPI_STARTUP_DIAG != 1
#error "SPI startup diagnostic flag must be 0 or 1"
#endif
#ifndef MESH_HIL_SPI3_RX_DELAY
#define MESH_HIL_SPI3_RX_DELAY -1
#endif
#if MESH_HIL_SPI3_RX_DELAY < -1 || MESH_HIL_SPI3_RX_DELAY > 7
#error "SPI3 sample delay must be -1 (unchanged) or 0..7"
#endif
#if MESH_HIL_SPI3_RX_DELAY >= 0
#if !MESH_HIL_SPI_STARTUP_DIAG || !defined(NRF52_PLATFORM)
#error "SPI3 sample delay requires the nRF52 SPI startup diagnostic"
#endif
#if !defined(SPI_32MHZ_INTERFACE) || SPI_32MHZ_INTERFACE != 1
#error "SPI3 sample delay requires the diagnostic SPI1/SPIM3 mapping"
#endif
#endif

#include "NrfRadioSpiReadProbe.h"

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

// Fixed 20-word ABI for private SWD reads, including before USB is usable.
// Each word is independently observable; this is not an atomic snapshot.
struct Capture {
  uint32_t magic, version, size_bytes, phase;
  uint32_t queries, first_query_result, first_query_enabled;
  uint32_t last_query_result, last_query_enabled;
  uint32_t begun, completed, refused, last_opcode, last_length;
  uint32_t actual_rx_delay;
  uint32_t packet_type_frames, packet_type_length, packet_type_rx[3];
};
static_assert(sizeof(Capture) == 80 && offsetof(Capture, begun) == 36
              && offsetof(Capture, actual_rx_delay) == 56
              && offsetof(Capture, packet_type_rx) == 68, "SPI startup capture ABI changed");
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

#if defined(MESH_HIL_SPI_READ_PROBE) && MESH_HIL_SPI_READ_PROBE
  // Only the separately gated post-initialization read probe can switch
  // these settings. Apply between completed frames through the normal HAL.
  bool setDiagnosticSpiFrequency(uint32_t hz) {
    if (hz != 8000000 && hz != 16000000) return false;
    spiSettings = SPISettings(hz, MSBFIRST, SPI_MODE0);
    return true;
  }
  uint32_t diagnosticSpiFrequencyRegister() const { return NRF_SPIM3->FREQUENCY; }
#endif

  void spiBeginTransaction() override {
#if defined(SPI_32MHZ_INTERFACE) && SPI_32MHZ_INTERFACE == 1
#if MESH_HIL_SPI3_RX_DELAY >= 0
    // The previous frame is complete and CS has not been selected. Configure
    // only the diagnostic SPIM3 while disabled; the normal base transaction
    // still owns mode/clock setup, enable, and its optional HIL guards.
    NRF_SPIM3->ENABLE = 0;
    NRF_SPIM3->IFTIMING.RXDELAY = MESH_HIL_SPI3_RX_DELAY;
#endif
#endif
    Nrf52BufferedRadioHal::spiBeginTransaction();
#if defined(SPI_32MHZ_INTERFACE) && SPI_32MHZ_INTERFACE == 1
    mesh::spistartup::mesh_hil_spi_startup.actual_rx_delay = NRF_SPIM3->IFTIMING.RXDELAY;
#endif
  }

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
    // Preserve real wire evidence for GetPacketType's opcode/status/data
    // bytes. Refused frames do not overwrite the last completed response.
    if (capture.last_opcode == 0x11) {
      ++capture.packet_type_frames;
      capture.packet_type_length = static_cast<uint32_t>(len);
      for (unsigned i = 0; i < 3; ++i)
        capture.packet_type_rx[i] = in && i < len ? in[i] : UINT32_MAX;
    }
    ++capture.completed;
    capture.phase = mesh::spistartup::Completed;
  }
};
#endif
