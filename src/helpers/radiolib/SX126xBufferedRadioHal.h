#pragma once

#ifndef MC_SX1262_SPI_HZ
#define MC_SX1262_SPI_HZ 8000000
#endif

#if defined(NRF52_PLATFORM)
  #include "Nrf52BufferedRadioHal.h"
  using SX126xBufferedRadioHalBase = Nrf52BufferedRadioHal;
#elif defined(ESP32_PLATFORM)
  #include "ESP32BufferedRadioHal.h"
  using SX126xBufferedRadioHalBase = ESP32BufferedRadioHal;
#elif defined(RP2040_PLATFORM)
  #include <hal/Arduino/ArduinoHal.h>
  // Earle Philhower's HardwareSPI bulk API retains full-duplex blocking
  // completion while filling/draining the controller FIFO in one call.
  class SX126xBufferedRadioHalBase : public ArduinoHal {
   public:
    explicit SX126xBufferedRadioHalBase(SPIClass& bus, uint32_t hz)
        : ArduinoHal(bus, SPISettings(hz, MSBFIRST, SPI_MODE0)) {}
    void spiTransfer(uint8_t* out, size_t len, uint8_t* in) override {
      if (len) spi->transfer(out, in, len);
    }
  };
#else
  #error "SX126x buffered radio SPI requires nRF52, ESP32 or RP2040"
#endif

// Keep the board's existing SPI controller and pin setup. Only the default
// SPI fallback owns begin/end; explicitly supplied buses remain board-owned.
// RadioLib still controls CS, BUSY, command status and IRQ acknowledgement.
class SX126xBufferedRadioHal : public SX126xBufferedRadioHalBase {
 public:
  explicit SX126xBufferedRadioHal(SPIClass& bus,
      uint32_t hz = MC_SX1262_SPI_HZ, bool initializeBus = false)
      : SX126xBufferedRadioHalBase(bus, hz) {
    initInterface = initializeBus;
  }
};
