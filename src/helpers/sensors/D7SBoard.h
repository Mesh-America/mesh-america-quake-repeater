#pragma once

#include <Arduino.h>

// Board-specific action taken once a D7S has been confirmed (it returned a valid state register).
//
// RAK3401 (RAK19007 base): IO2 (PIN_3V3_EN / WB_IO2) is the base board's enable for the shared
// 3V3_S rail and is also the RAK12027's open-drain INT2 when the sensor is in slot A. The stock
// firmware drives IO2 high, which would fight INT2, so release it to an input with the internal
// pull-up. This is a deliberate exception to the "never drop IO2" rule used elsewhere in this
// code base. While INT2 is asserted (power-up offset acquisition, earthquake processing) the
// enable can be pulled low; see docs/d7s-integration.md for what is and is not verified.
//
// A RAK4631 on a RAK19003 (the RAK10703 kit) does not need this: the sensor goes in slot D
// there, its INT2 is on IO6, and IO2 stays driven high to keep the sensor powered.
inline void d7sBoardOnConfirmed() {
#if defined(RAK_3401) && defined(PIN_3V3_EN)
  pinMode(PIN_3V3_EN, INPUT_PULLUP);
#endif
}
