#pragma once
#include <Arduino.h>
class TwoWire { public: void beginTransmission(int) {} int endTransmission() { return 0; } };
inline TwoWire Wire;
