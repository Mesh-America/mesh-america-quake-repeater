#pragma once

#include <stdint.h>
#include <string.h>

namespace mesh {
namespace power {

static const uint16_t MIN_CONFIGURED_MV = 2500;
static const uint16_t MIN_CUSTOM_MV = 2000;
static const uint16_t MAX_CONFIGURED_MV = 4200;

inline bool validThresholdPair(uint16_t boot, uint16_t low,
                               bool boot_off_allowed,
                               uint16_t minimum_mv = MIN_CONFIGURED_MV) {
  return (boot == 0 ? boot_off_allowed
                    : boot >= minimum_mv && boot <= MAX_CONFIGURED_MV)
      && (low == 0 || (low >= minimum_mv && low <= MAX_CONFIGURED_MV))
      && (low == 0 || (boot != 0 && low <= boot));
}

inline bool parseVoltageMillivolts(const char* value, uint16_t& mv,
                                   bool allow_off,
                                   uint16_t minimum_mv = MIN_CONFIGURED_MV) {
  if (value == nullptr) return false;
  if (allow_off && strcmp(value, "off") == 0) { mv = 0; return true; }
  if (*value == 0) return false;
  uint32_t number = 0;
  for (const char* p = value; *p; ++p) {
    if (*p < '0' || *p > '9') return false;
    number = number * 10 + (*p - '0');
    if (number > MAX_CONFIGURED_MV) return false;
  }
  if (number < minimum_mv) return false;
  mv = (uint16_t)number;
  return true;
}

inline uint8_t nextLowVoltageCount(uint8_t previous, uint16_t mv,
                                   uint16_t cutoff, bool external_power) {
  if (cutoff == 0 || external_power || mv <= 1000 || mv >= cutoff) return 0;
  return previous < 3 ? previous + 1 : 3;
}

inline uint8_t batteryPercent(uint16_t mv, uint16_t empty_mv,
                              uint16_t full_mv) {
  if (full_mv <= empty_mv) return 0;
  if (mv <= empty_mv) return 0;
  if (mv >= full_mv) return 100;
  return (uint8_t)(((uint32_t)(mv - empty_mv) * 100U)
                   / (full_mv - empty_mv));
}

// Keep a legacy voltage warning at the same fraction of the displayed battery
// range when the user selects a different chemistry or custom endpoints.
inline uint16_t remapBatteryWarningMillivolts(uint16_t old_warning,
                                              uint16_t old_empty,
                                              uint16_t old_full,
                                              uint16_t new_empty,
                                              uint16_t new_full) {
  if (old_full <= old_empty || new_full <= new_empty) return old_warning;
  if (old_warning <= old_empty) return new_empty;
  if (old_warning >= old_full) return new_full;
  const uint32_t old_span = old_full - old_empty;
  const uint32_t new_span = new_full - new_empty;
  return new_empty + (uint16_t)(((uint32_t)(old_warning - old_empty)
                                 * new_span + old_span / 2U) / old_span);
}

inline uint16_t calibratedMillivolts(uint16_t raw_mv,
                                     uint16_t multiplier_permille) {
  if (raw_mv == 0) return 0;
  const uint32_t value = ((uint32_t)raw_mv * multiplier_permille + 500U) / 1000U;
  return value > 65535U ? 65535U : (uint16_t)value;
}

} // namespace power
} // namespace mesh
