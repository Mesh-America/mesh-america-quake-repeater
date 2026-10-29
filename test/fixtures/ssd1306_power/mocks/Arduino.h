#pragma once

#include <assert.h>
#include <stddef.h>
#include <stdint.h>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1

inline uint8_t pin_levels[64] = {};
inline uint8_t pin_modes[64] = {};
inline uint32_t now_ms = 100;
inline uint32_t millis() { return now_ms; }
inline void pinMode(unsigned pin, uint8_t mode) {
  assert(pin < 64);
  pin_modes[pin] = mode;
}
inline void digitalWrite(unsigned pin, uint8_t level) {
  assert(pin < 64);
  pin_levels[pin] = level;
}
inline uint8_t digitalRead(unsigned pin) {
  assert(pin < 64);
  return pin_levels[pin];
}
