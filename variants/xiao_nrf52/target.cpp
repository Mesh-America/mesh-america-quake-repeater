#include <Arduino.h>
#include "target.h"
#include <helpers/radiolib/SX126xBufferedRadioHal.h>
#include <helpers/ArduinoHelpers.h>
#ifdef USE_CC310_HW_CRYPTO
  #include <helpers/NRF52Crypto.h>
#endif

static bool target_radio_available = false;

#ifdef DISPLAY_CLASS
  DISPLAY_CLASS display;
  MomentaryButton user_btn(PIN_USER_BTN, 1000, true, true);
#endif

XiaoNrf52Board board;

static SX126xBufferedRadioHal radioHal(SPI);
RADIO_CLASS radio = new Module(&radioHal, P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY);

WRAPPER_CLASS radio_driver(radio, board);

#ifdef DISABLE_I2C_RTC_SCAN
VolatileRTCClock rtc_clock;
#else
VolatileRTCClock fallback_clock;
AutoDiscoverRTCClock rtc_clock(fallback_clock);
#endif

EnvironmentSensorManager sensors;

bool radio_init() {
#ifndef DISABLE_I2C_RTC_SCAN
  rtc_clock.begin(Wire);
#endif

  target_radio_available = radio.std_init(&SPI);
  return target_radio_available;
}

mesh::LocalIdentity radio_new_identity() {
  if (target_radio_available) {
    RadioNoiseListener rng(radio);
    return mesh::LocalIdentity(&rng);
  }

  // Recovery-mode identity creation must not access a failed/absent carrier.
  // Preserve the seeded PRNG and independent CryptoCell entropy used by RAK3401.
  class XiaoIdentityRNG : public mesh::RNG {
  public:
    void random(uint8_t* dest, size_t size) override {
      for (size_t i = 0; i < size; ++i) {
        dest[i] = static_cast<uint8_t>(::random(0, 256));
        mesh::serviceIdentityGenerationProgress();
      }
#ifdef USE_CC310_HW_CRYPTO
      mesh::mixCC310Random(dest, size);
#endif
    }
  } rng;
  return mesh::LocalIdentity(&rng);
}
