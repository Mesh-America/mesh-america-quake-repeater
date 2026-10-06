#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace mesh {
namespace power {

// Parse volts without floating-point rounding, signs, exponents, or ignored
// suffixes. Millivolt precision keeps unsupported targets from being rounded
// into a supported charger setting.
inline bool parseChargeVolts(const char* value, uint16_t& millivolts) {
  if (!value || *value < '0' || *value > '9') return false;
  uint32_t whole = 0, fraction = 0;
  while (*value >= '0' && *value <= '9') {
    whole = whole * 10 + (*value++ - '0');
    if (whole > 65) return false;
  }
  unsigned digits = 0;
  if (*value == '.') {
    ++value;
    while (*value >= '0' && *value <= '9') {
      if (++digits > 3) return false;
      fraction = fraction * 10 + (*value++ - '0');
    }
    if (digits == 0) return false;
  }
  while (*value == ' ' || *value == '\t') ++value;
  if (*value) return false;
  while (digits++ < 3) fraction *= 10;
  const uint32_t result = whole * 1000 + fraction;
  if (result > 65535) return false;
  millivolts = static_cast<uint16_t>(result);
  return true;
}

inline bool chargeCommandKey(const char* text, const char* key) {
  const size_t length = strlen(key);
  return strncmp(text, key, length) == 0
      && (text[length] == 0 || text[length] == ' ' || text[length] == '\t');
}

// Shared by infrastructure, Companion, and Terminal Chat. Board code owns
// hardware validation and persistence; the CLI must not alter BMS protection
// settings to simulate an unsupported charger voltage.
template <typename Board>
bool handleBatteryChargeCommand(Board& board, const char* command,
                                char* reply, size_t reply_capacity) {
  if (!command || !reply || !reply_capacity) return false;
  while (*command == ' ' || *command == '\t') ++command;
  const bool get = strncmp(command, "get ", 4) == 0;
  const bool set = strncmp(command, "set ", 4) == 0;
  if (!get && !set) return false;
  const char* key = command + 4;
  const bool options = get && chargeCommandKey(key, "charge.voltage.options");
  if (!options && !chargeCommandKey(key, "charge.voltage")) return false;
  const char* value = key + strlen(options ? "charge.voltage.options" : "charge.voltage");
  while (*value == ' ' || *value == '\t') ++value;
  if (get && *value) {
    snprintf(reply, reply_capacity, "Error: usage get charge.voltage[.options]");
    return true;
  }
  const char* targets = board.getBatteryChargeTargetOptions();
  if (!targets) {
    snprintf(reply, reply_capacity, "Error: %s", board.getBatteryChargeTargetUnsupportedReason());
    return true;
  }
  if (options) {
    snprintf(reply, reply_capacity, "> %s V", targets);
    return true;
  }
  uint16_t millivolts = 0;
  if (get) {
    if (!board.getBatteryChargeTarget(millivolts)) {
      snprintf(reply, reply_capacity, "Error: charger read failed");
    } else {
      snprintf(reply, reply_capacity, "> %u.%03u V%s",
               static_cast<unsigned>(millivolts / 1000),
               static_cast<unsigned>(millivolts % 1000),
               board.batteryChargeTargetRestoreFailed() ? " (boot restore failed)" : "");
    }
    return true;
  }
  if (!parseChargeVolts(value, millivolts)) {
    snprintf(reply, reply_capacity, "Error: usage set charge.voltage <volts>");
  } else if (!board.supportsBatteryChargeTarget(millivolts)) {
    snprintf(reply, reply_capacity, "Error: unsupported target; allowed %s V", targets);
  } else if (!board.setBatteryChargeTarget(millivolts)) {
    snprintf(reply, reply_capacity, "Error: charge target not confirmed saved; check get charge.voltage");
  } else {
    snprintf(reply, reply_capacity, "OK - charge.voltage %u.%03u V (saved)",
             static_cast<unsigned>(millivolts / 1000),
             static_cast<unsigned>(millivolts % 1000));
  }
  return true;
}

} // namespace power
} // namespace mesh
