#pragma once

#include <RadioLib.h>

inline uint8_t sx126xMorsePaRamp() {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_PA_RAMP_US)
  constexpr unsigned requested_us = MESH_MORSE_HIL_PA_RAMP_US;
  static_assert(requested_us == 10 || requested_us == 20 || requested_us == 40
      || requested_us == 80 || requested_us == 200 || requested_us == 800
      || requested_us == 1700 || requested_us == 3400,
      "HIL SX126x PA ramp must be 10/20/40/80/200/800/1700/3400 microseconds");
  constexpr uint8_t requested = requested_us == 10 ? RADIOLIB_SX126X_PA_RAMP_10U
      : requested_us == 20 ? RADIOLIB_SX126X_PA_RAMP_20U
      : requested_us == 40 ? RADIOLIB_SX126X_PA_RAMP_40U
      : requested_us == 80 ? RADIOLIB_SX126X_PA_RAMP_80U
      : requested_us == 200 ? RADIOLIB_SX126X_PA_RAMP_200U
      : requested_us == 800 ? RADIOLIB_SX126X_PA_RAMP_800U
      : requested_us == 1700 ? RADIOLIB_SX126X_PA_RAMP_1700U
      : RADIOLIB_SX126X_PA_RAMP_3400U;
#else
  constexpr uint8_t requested = RADIOLIB_SX126X_PA_RAMP_3400U;
#endif
#ifdef SX126X_PA_RAMP_TIME
  // The hardware ramp encodings increase with duration. A lab override must
  // never defeat a board's slower external-PA requirement.
  constexpr uint8_t board_minimum = static_cast<uint8_t>(SX126X_PA_RAMP_TIME);
  return requested < board_minimum ? board_minimum : requested;
#else
  return requested;
#endif
}

// Set only the envelope ramp, using RadioLib's cached chip drive power. This
// preserves external-PA board calibration instead of treating user dBm as a
// raw PA drive level. A CW transmitter has no receive bandwidth to select.
inline int16_t setSX126xMorseRamp(SX126x* radio) {
  const int16_t status = radio->setPaRampTime(sx126xMorsePaRamp());
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_WARM_TX) && MESH_MORSE_HIL_WARM_TX
  // Establish XOSC before the first mark too. Do not borrow or overwrite the
  // scanner's standbyXOSC policy: normal final cleanup restores it unchanged.
  return status == RADIOLIB_ERR_NONE ? radio->standby(RADIOLIB_SX126X_STANDBY_XOSC) : status;
#else
  return status;
#endif
}

inline int16_t leaveSX126xMorseCarrier(SX126x* radio) {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_WARM_TX) && MESH_MORSE_HIL_WARM_TX
  return radio->standby(RADIOLIB_SX126X_STANDBY_XOSC);
#else
  return radio->standby();
#endif
}

inline int16_t restoreSX126xPacketRamp(SX126x* radio) {
#ifdef SX126X_PA_RAMP_TIME
  return radio->setPaRampTime(static_cast<uint8_t>(SX126X_PA_RAMP_TIME));
#else
  return radio->setPaRampTime(RADIOLIB_SX126X_PA_RAMP_200U);
#endif
}
