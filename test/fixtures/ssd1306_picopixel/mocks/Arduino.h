#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <string>
#define PROGMEM
#define pgm_read_byte(addr) (*(const uint8_t *)(addr))
#define HIGH 1
#define LOW 0
#define OUTPUT 1
using String = std::string;
class __FlashStringHelper;
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
using std::min;
using std::max;
inline float radians(float deg) { return deg * 0.017453292519943295f; }
