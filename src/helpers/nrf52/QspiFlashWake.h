#pragma once

#include "QspiFlashWakePolicy.h"

#if defined(NRF52_PLATFORM)
#include <Arduino.h>
#include <hal/nrf_gpio.h>
#include <hal/nrf_qspi.h>
#endif

namespace mesh {
namespace nrf52 {

#if defined(NRF52_PLATFORM)
inline void wakeQspiFlashBeforeActivate(const nrf_qspi_pins_t& pins) {
  // TASKS_ACTIVATE talks to the NOR before CINSTR is available. A sleeping
  // chip ignores that traffic and can leave activation waiting forever.
  // Send only the non-destructive 0xAB wake byte over mode-0 GPIO first.
  nrf_gpio_pin_clear(pins.sck_pin);
  nrf_gpio_pin_set(pins.csn_pin);
  nrf_gpio_pin_set(pins.io0_pin);
  if (pins.io2_pin != NRF_QSPI_PIN_NOT_CONNECTED) nrf_gpio_pin_set(pins.io2_pin);
  if (pins.io3_pin != NRF_QSPI_PIN_NOT_CONNECTED) nrf_gpio_pin_set(pins.io3_pin);

  nrf_gpio_cfg(pins.sck_pin, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
               NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  nrf_gpio_cfg(pins.csn_pin, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
               NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  nrf_gpio_cfg(pins.io0_pin, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
               NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  nrf_gpio_cfg(pins.io1_pin, NRF_GPIO_PIN_DIR_INPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
               NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  if (pins.io2_pin != NRF_QSPI_PIN_NOT_CONNECTED)
    nrf_gpio_cfg(pins.io2_pin, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
                 NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  if (pins.io3_pin != NRF_QSPI_PIN_NOT_CONNECTED)
    nrf_gpio_cfg(pins.io3_pin, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_DISCONNECT,
                 NRF_GPIO_PIN_NOPULL, NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);

  delayMicroseconds(1);
  nrf_gpio_pin_clear(pins.csn_pin);
  delayMicroseconds(1);
  for (uint8_t bit = 0; bit < 8u; bit++) {
    nrf_gpio_pin_write(pins.io0_pin, qspiReleaseFromDeepPowerDownBit(bit));
    delayMicroseconds(1);
    nrf_gpio_pin_set(pins.sck_pin);
    delayMicroseconds(1);
    nrf_gpio_pin_clear(pins.sck_pin);
    delayMicroseconds(1);
  }
  nrf_gpio_pin_set(pins.csn_pin);
  delayMicroseconds(QSPI_DPD_WAKE_GUARD_US);
}
#endif

} // namespace nrf52
} // namespace mesh
