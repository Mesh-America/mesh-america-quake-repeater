#pragma once

#include "../LedPolicy.h"
#include "ShutdownLeds.h"
#include <bluefruit.h>

namespace mesh_nrf52 {

inline bool& bluetoothLedReady() {
  static bool ready = false;
  return ready;
}

inline void applyBluetoothLedPolicy() {
#ifdef LED_BLUE
  if (LED_BLUE < 0 || static_cast<uint32_t>(LED_BLUE) >= PINS_COUNT
      || digitalPinToPinName(LED_BLUE) == 0xff) {
    Bluefruit.autoConnLed(false);
    return;
  }
#else
  Bluefruit.autoConnLed(false);
  return;
#endif
#ifdef DISABLE_BLE_LED
  const bool enable = false;
#else
  const bool enable = mesh::leds::enabled();
#endif
  Bluefruit.autoConnLed(enable);
  if (!enable) {
#ifdef LED_BLUE
    turnOffShutdownLed(LED_BLUE);
#endif
  } else if (bluetoothLedReady()) {
#if defined(RAK_BOARD) && defined(BLE_PIN_CODE)
    Bluefruit._setConnLed(false);
#else
    Bluefruit._setConnLed(Bluefruit.connected() != 0);
#endif
    if (Bluefruit.Advertising.isRunning()) Bluefruit._startConnLed();
  }
}

inline void bluetoothLedStarted() {
  bluetoothLedReady() = true;
  applyBluetoothLedPolicy();
}

} // namespace mesh_nrf52
