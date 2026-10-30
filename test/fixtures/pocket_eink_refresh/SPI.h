#pragma once
#include <Arduino.h>
#define MSBFIRST 1
#define SPI_MODE0 0
struct SPISettings { SPISettings(int, int, int) {} };
struct SPIClass { void begin() {} };
inline SPIClass SPI1;
