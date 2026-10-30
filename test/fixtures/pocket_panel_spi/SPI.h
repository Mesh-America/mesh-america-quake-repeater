#pragma once
#include <Arduino.h>
#define MSBFIRST 1
#define SPI_MODE0 0
struct SPISettings { SPISettings(unsigned long, int, int) {} };
struct SPIClass {
  void begin() {}
  void end() {}
  void beginTransaction(SPISettings) {}
  void endTransaction() {}
  uint8_t transfer(uint8_t value);
};
inline SPIClass SPI;
