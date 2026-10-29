#pragma once

#ifndef MESH_HIL_SPI_READ_PROBE
#define MESH_HIL_SPI_READ_PROBE 0
#endif
#if MESH_HIL_SPI_READ_PROBE != 0 && MESH_HIL_SPI_READ_PROBE != 1
#error "SPI read probe flag must be 0 or 1"
#endif
#if MESH_HIL_SPI_READ_PROBE
#if !defined(NRF52_PLATFORM) || !defined(MESH_HIL_SPI_STARTUP_DIAG) \
    || MESH_HIL_SPI_STARTUP_DIAG != 1 || !defined(MESH_HIL_PROFILE_TIMING) \
    || MESH_HIL_PROFILE_TIMING != 1
#error "SPI read probe requires nRF52 startup and profile timing diagnostics"
#endif
#if !defined(SPI_32MHZ_INTERFACE) || SPI_32MHZ_INTERFACE != 1 \
    || !defined(NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED) \
    || NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED != 1
#error "SPI read probe requires SPI1/SPIM3 and the explicit nrfx198 workaround"
#endif
#ifndef MC_RAK3401_SPI_HZ
#define MC_RAK3401_SPI_HZ 8000000
#endif
#if MC_RAK3401_SPI_HZ != 8000000
#error "SPI read probe must initialize the radio at 8 MHz"
#endif

#include <stddef.h>
#include <stdint.h>

namespace mesh { namespace spireadprobe {

static constexpr uint32_t ReadsPerPhase = 16;
static constexpr uint32_t BusyTimeoutMillis = 20;
struct PhaseCapture {
  uint32_t requested_hz, reads, api_ok, api_errors, lora_types, other_types;
  int32_t first_result, last_result;
  uint32_t first_type, last_type, first_rx[3], last_rx[3];
  uint32_t first_frequency, last_frequency;
  uint32_t refusals_before, refusals_after, queries_before, queries_after;
};
struct Capture {
  uint32_t magic, version, size_bytes, active_phase;
  uint32_t runs, complete, restored_hz, restored_frequency;
  PhaseCapture phases[3];
};
static_assert(sizeof(PhaseCapture) == 88 && sizeof(Capture) == 296
              && offsetof(Capture, phases) == 32, "SPI read probe capture ABI changed");
extern "C" {
extern volatile Capture mesh_hil_spi_read_probe;
}

inline bool trailingBaselineHealthy() {
  const auto& capture = mesh_hil_spi_read_probe;
  const auto& sample = capture.phases[2];
  return capture.complete && capture.restored_hz == 8000000
      && capture.restored_frequency == 0x80000000
      && sample.reads == ReadsPerPhase && sample.api_ok == ReadsPerPhase
      && sample.api_errors == 0 && sample.lora_types == ReadsPerPhase && sample.other_types == 0
      && sample.first_frequency == 0x80000000 && sample.last_frequency == 0x80000000
      && sample.refusals_after == sample.refusals_before
      && sample.queries_after - sample.queries_before == ReadsPerPhase;
}

// Only used immediately after successful radio initialization. Module keeps
// its ordinary BUSY, command-status and CS handling; there are no radio writes
// or resets between these reads. A temporary short timeout bounds each BUSY
// wait; nrfx's blocking DMA itself still relies on the existing watchdog.
template <typename Hal, typename Module, typename SpiCapture>
void run(Hal& hal, Module& module, const volatile SpiCapture& spi_capture) {
  auto& capture = mesh_hil_spi_read_probe;
  if (capture.runs) return;
  ++capture.runs;
  const auto original_timeout = module.spiConfig.timeout;
  module.spiConfig.timeout = BusyTimeoutMillis;
  const uint32_t frequencies[] = {8000000, 16000000, 8000000};
  for (unsigned phase = 0; phase < 3; ++phase) {
    capture.active_phase = phase;
    auto& sample = capture.phases[phase];
    sample.requested_hz = frequencies[phase];
    sample.refusals_before = spi_capture.refused;
    sample.queries_before = spi_capture.queries;
    (void)hal.setDiagnosticSpiFrequency(frequencies[phase]);
    for (unsigned read = 0; read < ReadsPerPhase; ++read) {
      const uint32_t previous_frames = spi_capture.packet_type_frames;
      uint8_t type = 0xff;
      const int32_t result = module.SPIreadStream(0x11, &type, 1, true, false);
      const uint32_t actual_frequency = hal.diagnosticSpiFrequencyRegister();
      ++sample.reads;
      if (result == 0) ++sample.api_ok;
      else ++sample.api_errors;
      if (type == 1) ++sample.lora_types;
      else ++sample.other_types;
      if (!read) {
        sample.first_result = result;
        sample.first_type = type;
        sample.first_frequency = actual_frequency;
      }
      sample.last_result = result;
      sample.last_type = type;
      sample.last_frequency = actual_frequency;
      for (unsigned byte = 0; byte < 3; ++byte) {
        // Refused/timed-out reads have no new wire response. Do not relabel
        // the previous completed packet-type frame as this read's evidence.
        const uint32_t raw = spi_capture.packet_type_frames != previous_frames
            ? spi_capture.packet_type_rx[byte] : UINT32_MAX;
        if (!read) sample.first_rx[byte] = raw;
        sample.last_rx[byte] = raw;
      }
    }
    sample.refusals_after = spi_capture.refused;
    sample.queries_after = spi_capture.queries;
  }
  // Also apply the restored setting without selecting CS or starting SPI.
  // This covers a final phase whose Module calls returned before transfer.
  (void)hal.setDiagnosticSpiFrequency(8000000);
  hal.spiBeginTransaction();
  hal.spiEndTransaction();
  module.spiConfig.timeout = original_timeout;
  capture.restored_hz = 8000000;
  capture.restored_frequency = hal.diagnosticSpiFrequencyRegister();
  capture.active_phase = UINT32_MAX;
  capture.complete = 1;
}

} } // namespace mesh::spireadprobe
#endif
