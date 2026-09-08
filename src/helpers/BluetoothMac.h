#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace mesh {
namespace companion {

static const size_t BLUETOOTH_MAC_BYTES = 6;
static const size_t BLUETOOTH_MAC_TEXT_SIZE = 18;

enum BluetoothMacMode : uint8_t {
  BLUETOOTH_MAC_DEFAULT = 0,
  BLUETOOTH_MAC_CUSTOM = 1,
  BLUETOOTH_MAC_RANDOM_SAVED = 2,
  BLUETOOTH_MAC_RANDOM_EVERY_BOOT = 3,
};

inline bool isValidBluetoothMacMode(uint8_t mode) {
  return mode <= BLUETOOTH_MAC_RANDOM_EVERY_BOOT;
}

inline bool bluetoothMacModeUsesSavedAddress(uint8_t mode) {
  return mode == BLUETOOTH_MAC_CUSTOM
      || mode == BLUETOOTH_MAC_RANDOM_SAVED;
}

inline bool hasCustomBluetoothMac(
    const uint8_t address[BLUETOOTH_MAC_BYTES]) {
  if (address == NULL) return false;
  for (size_t i = 0; i < BLUETOOTH_MAC_BYTES; i++) {
    if (address[i] != 0) return true;
  }
  return false;
}

// User-selected BLE identities are random-static addresses, not IEEE-assigned
// public addresses. The two most-significant bits must be one, while the
// remaining 46 bits may not be all zero or all one.
inline bool isValidBluetoothMac(
    const uint8_t address[BLUETOOTH_MAC_BYTES]) {
  if (address == NULL || (address[0] & 0xC0u) != 0xC0u) return false;

  bool payload_all_zero = (address[0] & 0x3Fu) == 0;
  bool payload_all_one = (address[0] & 0x3Fu) == 0x3Fu;
  for (size_t i = 1; i < BLUETOOTH_MAC_BYTES; i++) {
    payload_all_zero = payload_all_zero && address[i] == 0;
    payload_all_one = payload_all_one && address[i] == 0xFFu;
  }
  return !payload_all_zero && !payload_all_one;
}

// Convert six random bytes into a valid BLE random-static identity. This is
// deterministic for a given input so both saved-random and per-boot modes can
// use the platform's existing entropy source without platform-specific rules.
inline void makeRandomStaticBluetoothMac(
    uint8_t address[BLUETOOTH_MAC_BYTES]) {
  if (address == NULL) return;
  address[0] |= 0xC0u;
  if (!isValidBluetoothMac(address)) address[5] ^= 0x01u;
}

inline int bluetoothMacHexDigit(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

inline bool parseBluetoothMac(
    const char* text, uint8_t output[BLUETOOTH_MAC_BYTES]) {
  if (text == NULL || output == NULL || strlen(text) != 17) return false;
  const char separator = text[2];
  if (separator != ':' && separator != '-') return false;

  uint8_t parsed[BLUETOOTH_MAC_BYTES];
  for (size_t i = 0; i < BLUETOOTH_MAC_BYTES; i++) {
    const size_t offset = i * 3;
    const int high = bluetoothMacHexDigit(text[offset]);
    const int low = bluetoothMacHexDigit(text[offset + 1]);
    if (high < 0 || low < 0
        || (i + 1 < BLUETOOTH_MAC_BYTES
            && text[offset + 2] != separator)) {
      return false;
    }
    parsed[i] = static_cast<uint8_t>((high << 4) | low);
  }
  if (!isValidBluetoothMac(parsed)) return false;
  memcpy(output, parsed, sizeof(parsed));
  return true;
}

inline bool formatBluetoothMac(
    const uint8_t address[BLUETOOTH_MAC_BYTES], char* output,
    size_t output_size) {
  if (address == NULL || output == NULL
      || output_size < BLUETOOTH_MAC_TEXT_SIZE) {
    if (output != NULL && output_size != 0) output[0] = 0;
    return false;
  }

  static const char HEX_DIGITS[] = "0123456789ABCDEF";
  size_t cursor = 0;
  for (size_t i = 0; i < BLUETOOTH_MAC_BYTES; i++) {
    output[cursor++] = HEX_DIGITS[address[i] >> 4];
    output[cursor++] = HEX_DIGITS[address[i] & 0x0Fu];
    if (i + 1 < BLUETOOTH_MAC_BYTES) output[cursor++] = ':';
  }
  output[cursor] = 0;
  return true;
}

}  // namespace companion
}  // namespace mesh
