#include "LedPolicy.h"
#include <Arduino.h>
#include <target.h>

namespace mesh { namespace leds {

void applyStatusPolicy() {
  if (enabled()) return;
#if defined(PIN_STATUS_LED_R) && defined(PIN_STATUS_LED_G) && defined(PIN_STATUS_LED_B)
  analogWrite(PIN_STATUS_LED_R, 0);
  analogWrite(PIN_STATUS_LED_G, 0);
  analogWrite(PIN_STATUS_LED_B, 0);
#elif defined(PIN_STATUS_LED)
  if (PIN_STATUS_LED < 0) return;
#ifdef LED_STATE_ON
  digitalWrite(PIN_STATUS_LED, !LED_STATE_ON);
#else
  digitalWrite(PIN_STATUS_LED, LOW);
#endif
  pinMode(PIN_STATUS_LED, OUTPUT);
#endif
}

}} // namespace mesh::leds
