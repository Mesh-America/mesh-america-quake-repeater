#include <Arduino.h>
#include "target.h"
#include <helpers/ArduinoHelpers.h>
#include <helpers/nrf52/Nrf52HilSpim1Owner.h>
#if MC_NRF52_HIL_SPIM1_RADIO
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
#endif

RAKWismeshTagBoard board;

#ifndef PIN_USER_BTN
  #define PIN_USER_BTN (-1)
#endif

#ifdef DISPLAY_CLASS
  DISPLAY_CLASS display;
  MomentaryButton user_btn(PIN_USER_BTN, 1000, true, true);
#endif

#if MC_NRF52_HIL_SPIM1_RADIO
static Nrf52BufferedRadioHal radioHal(SPI, 8000000);
RADIO_CLASS radio = new Module(&radioHal, P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY);
#else
RADIO_CLASS radio = new Module(P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY, SPI);
#endif

WRAPPER_CLASS radio_driver(radio, board);

VolatileRTCClock fallback_clock;
AutoDiscoverRTCClock rtc_clock(fallback_clock);

#if ENV_INCLUDE_GPS
  #include <helpers/sensors/MicroNMEALocationProvider.h>
  MicroNMEALocationProvider nmea = MicroNMEALocationProvider(Serial1, &rtc_clock);
  EnvironmentSensorManager sensors = EnvironmentSensorManager(nmea);
#else
  EnvironmentSensorManager sensors;
#endif

bool radio_init() {
  rtc_clock.begin(Wire);
  return radio.std_init(&SPI);
}

mesh::LocalIdentity radio_new_identity() {
  RadioNoiseListener rng(radio);
  return mesh::LocalIdentity(&rng);  // create new random identity
}
