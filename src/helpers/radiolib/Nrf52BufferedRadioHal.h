#pragma once

#include <hal/Arduino/ArduinoHal.h>
#include "NrfRadioProfileExperimentConfig.h"

#ifndef MC_NRF_RADIO_PROFILE_PRIORITY
#define MC_NRF_RADIO_PROFILE_PRIORITY 0
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY
#include "NrfRadioPriorityLease.h"
#endif
#ifndef MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
#define MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD 0
#endif
#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
#include "NrfRadioUsbIrqGuard.h"
#endif

#ifndef MC_NRF_RADIO_BUSY_SPIN_POLLS
#define MC_NRF_RADIO_BUSY_SPIN_POLLS 0
#endif
#if MC_NRF_RADIO_BUSY_SPIN_POLLS < 0 || MC_NRF_RADIO_BUSY_SPIN_POLLS > 16
#error "nRF radio yield experiment requires a bounded 0..16 poll budget"
#endif

// nRF52840 SPIClass::transfer(uint8_t) starts one SPIM transaction per byte.
// RadioLib sends whole command buffers; keep its CS, BUSY, and status handling
// but transfer each buffer in one SPIM transaction. LR1110 supports 16 MHz SPI.
class Nrf52BufferedRadioHal : public ArduinoHal {
#if MC_NRF_RADIO_BUSY_SPIN_POLLS > 0
  uint8_t _busy_spin_polls_remaining = 0;
#endif
public:
  explicit Nrf52BufferedRadioHal(SPIClass& bus, uint32_t hz = 16000000)
      : ArduinoHal(bus, SPISettings(hz, MSBFIRST, SPI_MODE0)) {}

#if MC_NRF_RADIO_PROFILE_PRIORITY || MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
  void spiBeginTransaction() override {
    // Check before RadioLib lowers CS, so restoring task priority does not
    // suspend this task with a newly selected, unclocked radio command.
#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
    mesh::radiousb::beforeFrame();
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY
    mesh::radiopriority::beforeFrame();
#endif
    ArduinoHal::spiBeginTransaction();
  }
#endif

  void spiTransfer(uint8_t* out, size_t len, uint8_t* in) override {
    if (!len) return;
    spi->transfer(out, in, len);
#if MC_NRF_RADIO_BUSY_SPIN_POLLS > 0
    _busy_spin_polls_remaining = MC_NRF_RADIO_BUSY_SPIN_POLLS;
#endif
  }

#if MC_NRF_RADIO_BUSY_SPIN_POLLS > 0 || MC_NRF_RADIO_PROFILE_PRIORITY || MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
  // Diagnostic only, off by default. RadioLib calls yield() during SPI BUSY
  // polls and other waits. Spend at most N non-yielding polls after a real
  // frame, then delegate every call until another frame resets the budget.
  // An unused budget can reach a later non-BUSY wait; this is not BUSY-only
  // detection. No GPIO reads, status checks, timeouts or interrupts change.
  void yield() override {
#if MC_NRF_RADIO_PROFILE_PRIORITY
    // In the explicit combined test, suppress a cooperative task switch
    // before the USB guard can yield to the already queued USB worker.
    const auto decision = mesh::radiopriority::beforeYield();
    if (decision == mesh::radiopriority::Suppress) return;
#endif
#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
    if (mesh::radiousb::beforeYield()) {
      // Normal Arduino yield flushes TinyUSB CDC. While its IRQ is deferred,
      // retain task scheduling without entering that USB flush/mutex path.
      taskYIELD();
      return;
    }
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY
    // Expiry can restore priority while the independent USB deadline still
    // owns its IRQ. Always consult that guard before a normal CDC flush.
    if (decision == mesh::radiopriority::Expired) {
      ArduinoHal::yield();
      return;
    }
#endif
#if MC_NRF_RADIO_BUSY_SPIN_POLLS > 0
    if (_busy_spin_polls_remaining) {
      --_busy_spin_polls_remaining;
      return;
    }
#endif
    ArduinoHal::yield();
  }
#endif
};
