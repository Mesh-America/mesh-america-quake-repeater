#pragma once

#include <math.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "CLICommandUtils.h"

namespace mesh { namespace power {

// New ADC backends use a correction relative to their original conversion.
// Existing board-specific absolute multipliers retain their own units.
inline bool validRelativeBatteryMultiplier(float multiplier) {
  return isfinite(multiplier) && (multiplier == 0.0f
      || (multiplier >= 0.5f && multiplier <= 1.5f));
}

inline uint16_t scaleBatteryMillivolts(uint16_t millivolts, float multiplier) {
  if (millivolts == 0 || !isfinite(multiplier) || multiplier <= 0.0f)
    return millivolts;
  const float scaled = millivolts * multiplier;
  if (scaled >= 65535.0f) return UINT16_MAX;
  return static_cast<uint16_t>(scaled + 0.5f);
}

// Volts with millivolt precision. Require a measured value; neither chemistry
// nor charger regulation voltage supplies a calibration reference.
inline bool parseBatteryReferenceMillivolts(const char* text, uint16_t& result) {
  if (!text || *text < '0' || *text > '9') return false;
  uint32_t whole = 0, fraction = 0;
  while (*text >= '0' && *text <= '9') {
    whole = whole * 10 + static_cast<unsigned>(*text++ - '0');
    if (whole > 65) return false;
  }
  unsigned digits = 0;
  if (*text == '.') {
    ++text;
    while (*text >= '0' && *text <= '9') {
      if (++digits > 3) return false;
      fraction = fraction * 10 + static_cast<unsigned>(*text++ - '0');
    }
    if (digits == 0) return false;
  }
  while (*text == ' ' || *text == '\t') ++text;
  if (*text) return false;
  while (digits++ < 3) fraction *= 10;
  const uint32_t millivolts = whole * 1000 + fraction;
  if (millivolts == 0 || millivolts > UINT16_MAX) return false;
  result = static_cast<uint16_t>(millivolts);
  return true;
}

// Setter owns application, checked persistence and rollback. It leaves a
// useful error in reply when it fails. This keeps nRF52 boot-voltage policy
// and legacy absolute multiplier storage authoritative in their own roles.
template <typename Board, typename Setter>
bool handleBatteryCalibrationCommand(Board& board, const char* command,
                                     char* reply, size_t capacity,
                                     Setter set_multiplier) {
  if (!command || !reply || capacity == 0) return false;
  while (*command == ' ' || *command == '\t') ++command;
  static const char key[] = "battery calibrate";
  const size_t length = sizeof(key) - 1;
  if (strncmp(command, key, length) != 0
      || (command[length] && command[length] != ' ' && command[length] != '\t'))
    return false;
  const char* value = command + length;
  while (*value == ' ' || *value == '\t') ++value;
  const float previous = board.getAdcMultiplier();
  if (!isfinite(previous) || previous <= 0.0f) {
    mesh::cli::formatError(reply, capacity, "unsupported");
    return true;
  }
  const char* reset_end = value;
  if (strncmp(value, "reset", 5) == 0) {
    reset_end = value + 5;
    while (*reset_end == ' ' || *reset_end == '\t') ++reset_end;
    if (*reset_end == 0) {
      *reply = 0;
      if (set_multiplier(0.0f, reply, capacity))
        snprintf(reply, capacity, "OK - defaults (saved)");
      else if (*reply == 0)
        mesh::cli::formatError(reply, capacity, "save failed");
      return true;
    }
  }
  uint16_t reference = 0;
  if (!parseBatteryReferenceMillivolts(value, reference)) {
    mesh::cli::formatError(reply, capacity, "use battery calibrate <volts>|reset");
    return true;
  }
  const uint16_t reported = board.getBattMilliVolts();
  if (reported == 0 || reported == UINT16_MAX) {
    mesh::cli::formatError(reply, capacity, "no battery reading");
    return true;
  }
  const float correction = static_cast<float>(reference) / reported;
  if (!validRelativeBatteryMultiplier(correction)) {
    snprintf(reply, capacity, "Error: use 50%%-150%% of reading");
    return true;
  }
  const float multiplier = previous * correction;
  if (!isfinite(multiplier) || multiplier <= 0.0f) {
    mesh::cli::formatError(reply, capacity, "invalid multiplier");
    return true;
  }
  *reply = 0;
  if (set_multiplier(multiplier, reply, capacity)) {
    snprintf(reply, capacity, "OK - %u.%03u V; ADC %.6f (saved)",
             static_cast<unsigned>(reference / 1000),
             static_cast<unsigned>(reference % 1000), board.getAdcMultiplier());
  } else if (*reply == 0) {
    mesh::cli::formatError(reply, capacity, "save failed");
  }
  return true;
}

}} // namespace mesh::power
