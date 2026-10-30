#pragma once

#include <stddef.h>
#include <stdint.h>
#include "RS232Heartbeat.h"

namespace mesh {
namespace bridge {
namespace rs232power {

static constexpr uint16_t DEFAULT_IDLE_SECONDS = 300;
static constexpr uint16_t MIN_IDLE_SECONDS = 60;
static constexpr uint16_t MAX_IDLE_SECONDS = 3600;
static constexpr size_t PREFS_SIZE = 10;

inline void sanitize(uint8_t& heartbeat, uint8_t& autosleep, uint16_t& idle) {
  heartbeat = heartbeat == 1 ? 1 : 0;
  autosleep = autosleep <= 2 ? autosleep : 0;
  if (idle < MIN_IDLE_SECONDS || idle > MAX_IDLE_SECONDS) idle = DEFAULT_IDLE_SECONDS;
}

// Append-only, checked modes. A missing, torn or foreign tail defaults to
// negotiated standby, which never switches off an unconfirmed stock link.
inline void encodePrefs(uint8_t* out, uint8_t heartbeat, uint8_t autosleep, uint16_t idle) {
  out[0] = 'R'; out[1] = 'S'; out[2] = 'P'; out[3] = 1;
  out[4] = heartbeat == 1 ? 1 : 0;
  out[5] = autosleep <= 2 ? autosleep : 0;
  if (idle < MIN_IDLE_SECONDS || idle > MAX_IDLE_SECONDS) idle = DEFAULT_IDLE_SECONDS;
  out[6] = static_cast<uint8_t>(idle >> 8);
  out[7] = static_cast<uint8_t>(idle);
  const uint16_t crc = rs232heartbeat::checksum(out, 8);
  out[8] = static_cast<uint8_t>(crc >> 8);
  out[9] = static_cast<uint8_t>(crc);
}

inline bool decodePrefs(const uint8_t* in, size_t size, uint8_t& heartbeat,
                        uint8_t& autosleep, uint16_t& idle) {
  if (!in || size != PREFS_SIZE || in[0] != 'R' || in[1] != 'S'
      || in[2] != 'P' || in[3] != 1 || in[4] > 1 || in[5] > 2) return false;
  const uint16_t seconds = static_cast<uint16_t>((in[6] << 8) | in[7]);
  const uint16_t crc = static_cast<uint16_t>((in[8] << 8) | in[9]);
  if (seconds < MIN_IDLE_SECONDS || seconds > MAX_IDLE_SECONDS
      || crc != rs232heartbeat::checksum(in, 8)) return false;
  heartbeat = in[4];
  autosleep = in[5];
  idle = seconds;
  return true;
}

} // namespace rs232power
} // namespace bridge
} // namespace mesh
