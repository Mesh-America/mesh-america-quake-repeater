#pragma once

#include <stdint.h>

namespace mesh {
namespace gps {

static const uint32_t DEFAULT_UPDATE_INTERVAL_SEC = 1;
static const uint32_t MAX_UPDATE_INTERVAL_SEC = 24UL * 60UL * 60UL;
static const uint16_t MAX_SYNC_INTERVAL_HOURS = 14U * 24U;

// Saturate while parsing, not after an overflowing atoi/strtoul. Still inspect
// every character so an oversized value with trailing junk is never accepted.
inline bool parseSyncIntervalHours(const char* value, uint16_t& configured_hours) {
  if (value == nullptr || *value == 0) return false;
  uint16_t parsed = 0;
  for (const char* p = value; *p; ++p) {
    if (*p < '0' || *p > '9') return false;
    const uint16_t next = parsed * 10U + static_cast<uint16_t>(*p - '0');
    parsed = next > MAX_SYNC_INTERVAL_HOURS ? MAX_SYNC_INTERVAL_HOURS : next;
  }
  if (parsed == 0) return false;
  configured_hours = parsed;
  return true;
}

inline bool parseUpdateInterval(const char* value, uint32_t& configured_sec) {
  if (value == nullptr || *value == 0) return false;

  uint32_t parsed = 0;
  for (const char* p = value; *p; ++p) {
    if (*p < '0' || *p > '9') return false;
    uint32_t digit = (uint32_t)(*p - '0');
    if (parsed > (MAX_UPDATE_INTERVAL_SEC - digit) / 10UL) return false;
    parsed = parsed * 10UL + digit;
  }

  configured_sec = parsed;
  return true;
}

inline uint32_t effectiveUpdateIntervalSec(uint32_t configured_sec) {
  return configured_sec == 0 ? DEFAULT_UPDATE_INTERVAL_SEC : configured_sec;
}

inline uint32_t updateIntervalMillis(uint32_t configured_sec) {
  return effectiveUpdateIntervalSec(configured_sec) * 1000UL;
}

} // namespace gps
} // namespace mesh
