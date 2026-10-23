#include "BatteryCalibrationStore.h"
#include "BatteryCalibration.h"
#include "CheckedSettingsFile.h"
#include "CLICommandUtils.h"
#include "PersistentStoreFormat.h"
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#include "AtomicFileWriter.h"
#else
#include "ContactFileTransaction.h"
#endif
#if defined(NRF52_POWER_MANAGEMENT)
#include "NRF52VoltagePolicy.h"
#endif
#include <math.h>
#include <stdio.h>
#include <string.h>

#if BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY && !defined(NRF52_POWER_MANAGEMENT)
#error "Policy-only battery calibration requires NRF52_POWER_MANAGEMENT"
#endif

namespace mesh { namespace power {
namespace {
#if !BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY
FILESYSTEM* calibration_fs = nullptr;
const char* const calibration_path = "/battery_cal";
#endif

bool usesVoltagePolicy() {
#if defined(NRF52_POWER_MANAGEMENT)
  return voltagePolicySupported();
#else
  return false;
#endif
}

#if !BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY
void encode(float multiplier, uint8_t (&data)[12]) {
  memcpy(data, "ADC1", 4);
  static_assert(sizeof(multiplier) == sizeof(uint32_t), "ADC record needs 32-bit float");
  uint32_t bits;
  memcpy(&bits, &multiplier, sizeof(bits));
  storage::writeLE32(data + 4, bits);
  storage::writeLE32(data + 8, storage::updateCRC32(0xffffffffUL, data, 8));
}

bool readMultiplier(float& multiplier) {
  uint8_t data[12];
  if (!storage::readFixedSettingsFile(calibration_fs, calibration_path, data, sizeof(data))
      || memcmp(data, "ADC1", 4) != 0
      || storage::readLE32(data + 8) != storage::updateCRC32(0xffffffffUL, data, 8)) return false;
  const uint32_t bits = storage::readLE32(data + 4);
  memcpy(&multiplier, &bits, sizeof(bits));
  return isfinite(multiplier) && multiplier >= 0.0f && multiplier <= 10.0f;
}

bool saveMultiplier(float multiplier) {
  if (!calibration_fs) return false;
  uint8_t data[12];
  encode(multiplier, data);
#if defined(NRF52_PLATFORM)
  return storage::writeCheckedSettingsFile(calibration_fs, calibration_path,
      data, sizeof(data)) == AtomicFileWriter::Outcome::Committed;
#else
  uint8_t verified[12];
#if defined(STM32_PLATFORM)
  AtomicFileWriter file(calibration_fs, calibration_path);
#else
  ContactFileTransaction file(calibration_fs, calibration_path);
#endif
  if (!file || file.write(data, sizeof(data)) != sizeof(data) || !file.commit()) return false;
  return storage::readFixedSettingsFile(calibration_fs, calibration_path,
                                         verified, sizeof(verified))
      && memcmp(data, verified, sizeof(data)) == 0;
#endif
}
#endif
} // namespace

bool beginBatteryCalibrationStore(MainBoard& board, FILESYSTEM* fs) {
#if BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY
  // A tagged board must finish its boot policy initialization first. Even a
  // missing/corrupt policy file initializes safe defaults; never silently
  // select a second calibration store if the board lifecycle is incomplete.
  (void)board;
  (void)fs;
  return usesVoltagePolicy();
#else
  calibration_fs = fs;
  if (usesVoltagePolicy() || board.getAdcMultiplier() <= 0.0f) return true;
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  if (!fs || !ContactFileTransaction::recover(fs, calibration_path)) return false;
#endif
  if (!fs) return false;
  if (!fs->exists(calibration_path)) return true;
  float multiplier;
  return readMultiplier(multiplier) && board.setAdcMultiplier(multiplier);
#endif
}

bool setStoredAdcMultiplier(MainBoard& board, float multiplier,
                            char* reply, size_t capacity) {
  if (!isfinite(multiplier) || multiplier < 0.0f || multiplier > 10.0f) {
    mesh::cli::formatError(reply, capacity, "multiplier 0-10");
    return false;
  }
  if (board.getAdcMultiplier() <= 0.0f) {
    mesh::cli::formatError(reply, capacity, "unsupported");
    return false;
  }
#if defined(NRF52_POWER_MANAGEMENT)
  if (usesVoltagePolicy()) {
    return setConfiguredAdcMultiplier(multiplier, reply, capacity);
  }
#endif
#if BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY
  mesh::cli::formatError(reply, capacity, "voltage policy unsupported");
  return false;
#else
  const float previous = board.getAdcMultiplier();
  if (!board.setAdcMultiplier(multiplier)) {
    mesh::cli::formatError(reply, capacity, "invalid multiplier");
    return false;
  }
  if (!saveMultiplier(multiplier)) {
    const bool restored = board.setAdcMultiplier(previous);
    snprintf(reply, capacity, "%s", restored
        ? "Error: save unconfirmed; reboot may differ"
        : "Error: save unconfirmed; runtime restore failed; reboot may differ");
    return false;
  }
  if (multiplier == 0.0f) snprintf(reply, capacity, "OK - defaults (saved)");
  else snprintf(reply, capacity, "OK - ADC %.3f (saved)", multiplier);
  return true;
#endif
}

bool handleStoredAdcMultiplierCommand(MainBoard& board, const char* command,
                                      char* reply, size_t capacity) {
  if (!command || !reply || !capacity) return false;
  const bool get = strncmp(command, "get ", 4) == 0;
  const bool set = strncmp(command, "set ", 4) == 0;
  if (!get && !set) return false;
  const char* key = command + 4;
  if (strncmp(key, "adc.multiplier", 14) != 0
      || (key[14] && key[14] != ' ' && key[14] != '\t')) return false;
  if (board.getAdcMultiplier() <= 0.0f) {
    mesh::cli::formatError(reply, capacity, "unsupported");
    return true;
  }
#if BATTERY_CALIBRATION_VOLTAGE_POLICY_ONLY
  return handleVoltagePolicyCommand(command, reply, capacity);
#else
#if defined(NRF52_POWER_MANAGEMENT)
  if (usesVoltagePolicy()) return handleVoltagePolicyCommand(command, reply, capacity);
#endif
  const char* value = key + 14;
  while (*value == ' ' || *value == '\t') ++value;
  if (get) {
    if (*value) mesh::cli::formatError(reply, capacity, "usage get adc.multiplier");
    else if (board.getAdcMultiplier() <= 0.0f) mesh::cli::formatError(reply, capacity, "unsupported");
    else snprintf(reply, capacity, "> %.3f", board.getAdcMultiplier());
  } else {
    float multiplier;
    if (!cli::parseDecimalStrict(value, multiplier))
      mesh::cli::formatError(reply, capacity, "invalid multiplier");
    else setStoredAdcMultiplier(board, multiplier, reply, capacity);
  }
  return true;
#endif
}

bool handleStoredBatteryCalibrationCommand(MainBoard& board, const char* command,
                                           char* reply, size_t capacity) {
  if (handleBatteryCalibrationCommand(board, command, reply, capacity,
        [&board](float multiplier, char* result, size_t result_capacity) {
          return setStoredAdcMultiplier(board, multiplier, result, result_capacity);
        })) return true;
  return handleStoredAdcMultiplierCommand(board, command, reply, capacity);
}
}} // namespace mesh::power
