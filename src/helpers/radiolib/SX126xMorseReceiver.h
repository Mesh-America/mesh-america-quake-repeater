#pragma once

#include <RadioLib.h>
#include "../MorseRx.h"

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_PACKET_GATING)
static_assert(MESH_MORSE_HIL_PACKET_GATING == 0 || MESH_MORSE_HIL_PACKET_GATING == 1,
              "HIL GFSK packet gating must be 0 or 1");
#endif

// Real GFSK 4.8 kHz receive filter, not a LoRa symbol/preamble detector.
// Keep the board's actual reference supply and regulator policy across the
// native one-time modem reset. No RF is transmitted by this preparation.
template<class RadioT>
int16_t prepareSX126xMorseReceiver(RadioT* radio, float frequency_mhz) {
  const float tcxo_voltage = radio->tcxoVoltage;
  const bool use_ldo = radio->useRegulatorLDO;
  const bool standby_xosc = radio->standbyXOSC;
  const bool boosted_gain = radio->rxBoostedGainMode;
  radio->standbyXOSC = false; // TCXO/DIO3 is not restored until beginFSK
  const int16_t begin_status = radio->beginFSK(
      frequency_mhz, mesh::MorseRx::ReceiverBitRateKbps, 0.6f, 4.8f, 2, 16, tcxo_voltage, use_ldo);
  radio->standbyXOSC = standby_xosc;
  if (begin_status != RADIOLIB_ERR_NONE) return begin_status;
  int16_t status;
#ifdef SX126X_CURRENT_LIMIT
  status = radio->setCurrentLimit(SX126X_CURRENT_LIMIT);
  if (status != RADIOLIB_ERR_NONE) return status;
#endif
#ifdef SX126X_DIO2_AS_RF_SWITCH
  status = radio->setDio2AsRfSwitch(SX126X_DIO2_AS_RF_SWITCH);
  if (status != RADIOLIB_ERR_NONE) return status;
#endif
#if defined(SX126X_RXEN) || defined(SX126X_TXEN)
  radio->setRfSwitchPins(
#ifdef SX126X_RXEN
      SX126X_RXEN,
#else
      RADIOLIB_NC,
#endif
#ifdef SX126X_TXEN
      SX126X_TXEN
#else
      RADIOLIB_NC
#endif
  );
#endif
#if !(defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_PACKET_GATING) && MESH_MORSE_HIL_PACKET_GATING)
  // The default no-lock packet tuple is retained unchanged. The isolated HIL
  // comparison instead keeps beginFSK's ordinary preamble/sync/CRC settings;
  // Semtech's spectral-scan example reads instant RSSI before packet lock.
  uint8_t unused_sync = 0;
  status = radio->setSyncWord(&unused_sync, 0);
  if (status != RADIOLIB_ERR_NONE) return status;
  status = radio->setCRC(0);
  if (status != RADIOLIB_ERR_NONE) return status;
#endif
  // No Morse data uses the FSK packet parser. Avoid random noise bytes making
  // arbitrarily short variable-length frames while sampling continuous power.
  status = radio->fixedPacketLengthMode(255);
  if (status != RADIOLIB_ERR_NONE) return status;
  status = radio->setMorseFastRssi();
  if (status != RADIOLIB_ERR_NONE) return status;
  // Boards can set the native gain directly at initialization, without an
  // exposed CLI/cache setting (notably integrated STM32WL targets). Preserve
  // that actual policy too; a valid wrapper cache is applied afterwards.
  status = radio->setRxBoostedGainMode(boosted_gain);
  if (status != RADIOLIB_ERR_NONE) return status;
  // The wrapper restores the cached gain while still in standby, then enters
  // RX through its dedicated start hook. No mid-RX gain/AGC mutation.
  return RADIOLIB_ERR_NONE;
}
