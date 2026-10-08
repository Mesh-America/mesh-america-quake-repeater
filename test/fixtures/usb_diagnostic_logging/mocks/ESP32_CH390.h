#pragma once

#include <Arduino.h>

#define ETH_MISO_PIN 1
#define ETH_MOSI_PIN 2
#define ETH_SCLK_PIN 3
#define ETH_CS_PIN 4
#define ETH_INT_PIN 5

struct ch390_config_t {
  int spi_miso_gpio = 0;
  int spi_mosi_gpio = 0;
  int spi_sck_gpio = 0;
  int spi_cs_gpio = 0;
  int int_gpio = 0;
};

#define CH390_DEFAULT_CONFIG() ch390_config_t{}

class MockCh390 {
 public:
  bool valid_hostname = false;
  unsigned begins = 0;
  bool setHostname(const char*) const { return valid_hostname; }
  bool begin(const ch390_config_t&) { ++begins; return true; }
};

extern MockCh390 CH390;
