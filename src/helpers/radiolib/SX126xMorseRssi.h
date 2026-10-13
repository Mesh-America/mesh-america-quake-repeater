#pragma once

#include <RadioLib.h>

inline int16_t setSX126xMorseRssiWindow(SX126x* radio) {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_RSSI_WINDOW)
  static_assert(MESH_MORSE_HIL_RSSI_WINDOW >= 0 && MESH_MORSE_HIL_RSSI_WINDOW <= 7,
                "SX126x RSSI averaging exponent must fit bits4:2");
  constexpr uint8_t window = MESH_MORSE_HIL_RSSI_WINDOW;
#else
  constexpr uint8_t window = 0;
#endif
  // SPIsetRegValue takes an already positioned register value, not a logical
  // field value. Window exponent2 is0x08 in RSSI_AVG_WINDOW[4:2], not0x02.
  return radio->getMod()->SPIsetRegValue(RADIOLIB_SX126X_REG_RSSI_AVG_WINDOW,
      static_cast<uint8_t>(window << 2), 4, 2);
}
