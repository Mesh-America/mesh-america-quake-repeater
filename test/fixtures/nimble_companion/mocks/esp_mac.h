#pragma once
#include <stdint.h>
#include <string.h>
inline int esp_efuse_mac_get_default(uint8_t* address) {
  const uint8_t factory[] = {0x44, 0x1b, 0xf6, 0x69, 0xcf, 0x98};
  memcpy(address, factory, sizeof(factory));
  return 0;
}
