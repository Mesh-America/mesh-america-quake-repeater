#include <Arduino.h>
#include "target.h"
#include <helpers/radiolib/SX126xBufferedRadioHal.h>
#include <helpers/sensors/MicroNMEALocationProvider.h>

ThinknodeM5Board board;

#if defined(P_LORA_SCLK)
  static SPIClass spi;
  static SX126xBufferedRadioHal radio_hal(spi);
  RADIO_CLASS radio = new Module(&radio_hal, P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY);
#else
  static SX126xBufferedRadioHal radio_hal(SPI, MC_SX1262_SPI_HZ, true);
  RADIO_CLASS radio = new Module(&radio_hal, P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY);
#endif

WRAPPER_CLASS radio_driver(radio, board);

ESP32RTCClock fallback_clock;
AutoDiscoverRTCClock rtc_clock(fallback_clock);

#ifdef ENV_INCLUDE_GPS
MicroNMEALocationProvider nmea = MicroNMEALocationProvider(Serial1, &rtc_clock);
EnvironmentSensorManager sensors = EnvironmentSensorManager(nmea);
#else
EnvironmentSensorManager sensors = EnvironmentSensorManager();
#endif

#ifdef DISPLAY_CLASS
  DISPLAY_CLASS display;
  MomentaryButton user_btn(PIN_USER_BTN, 1000, true);
#endif

bool radio_init() {
  fallback_clock.begin();
  rtc_clock.begin(Wire);
  pinMode(P_LORA_EN, OUTPUT);
  digitalWrite(P_LORA_EN, HIGH);
  #if defined(P_LORA_SCLK)
  spi.begin(P_LORA_SCLK, P_LORA_MISO, P_LORA_MOSI);
  return radio.std_init(&spi);
#else
  return radio.std_init();
#endif
}

mesh::LocalIdentity radio_new_identity() {
  RadioNoiseListener rng(radio);
  return mesh::LocalIdentity(&rng);  // create new random identity
}


