#include "CommonCLI.h"
#include "CheckedSettingsFile.h"
#include <MeshCore.h>
#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
#include "NRF52VoltagePolicy.h"
#endif
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#include "AtomicFileWriter.h"
#else
#include "ContactFileTransaction.h"
#endif

namespace {
const char* const BATTERY_FORWARD_PATH = "/battery_forward";

bool readBatteryForwarding(FILESYSTEM* fs, const char* path,
                          mesh::batteryforward::Settings& settings) {
  uint8_t bytes[mesh::batteryforward::RecordSize];
  return mesh::storage::readFixedSettingsFile(fs, path, bytes, sizeof(bytes))
      && mesh::batteryforward::decode(bytes, sizeof(bytes), settings);
}
}

void CommonCLI::loadBatteryForwarding(FILESYSTEM* fs) {
  _battery_forward_fs = fs;
  _battery_forward_settings = mesh::batteryforward::Settings{};
  _battery_forward_state = mesh::batteryforward::State{};
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  if (!mesh::ContactFileTransaction::recover(fs, BATTERY_FORWARD_PATH)) {
    _battery_forward_fs = nullptr;
    return;
  }
#endif
  mesh::batteryforward::Settings loaded;
  if (readBatteryForwarding(fs, BATTERY_FORWARD_PATH, loaded)
      || readBatteryForwarding(fs, "/battery_forward.bak", loaded))
    _battery_forward_settings = loaded;
}

bool CommonCLI::saveBatteryForwarding(const mesh::batteryforward::Settings& settings) {
  if (!_battery_forward_fs || !mesh::batteryforward::validSettings(settings)) return false;
  uint8_t bytes[mesh::batteryforward::RecordSize];
  mesh::batteryforward::encode(bytes, settings);
#if defined(NRF52_PLATFORM)
  return mesh::storage::writeCheckedSettingsFile(_battery_forward_fs, BATTERY_FORWARD_PATH,
      bytes, sizeof(bytes)) == mesh::AtomicFileWriter::Outcome::Committed;
#else
#if defined(STM32_PLATFORM)
  mesh::AtomicFileWriter writer(_battery_forward_fs, BATTERY_FORWARD_PATH);
#else
  mesh::ContactFileTransaction writer(_battery_forward_fs, BATTERY_FORWARD_PATH);
#endif
  if (!writer || writer.write(bytes, sizeof(bytes)) != sizeof(bytes) || !writer.commit()) return false;
  uint8_t verified[sizeof(bytes)];
  return mesh::storage::readFixedSettingsFile(_battery_forward_fs, BATTERY_FORWARD_PATH,
      verified, sizeof(verified)) && memcmp(bytes, verified, sizeof(bytes)) == 0;
#endif
}

uint16_t CommonCLI::batteryEmptyMv() const {
#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
  return mesh::power::configuredEmpty();
#else
#ifdef BATT_MIN_MILLIVOLTS
  const uint16_t compiled = BATT_MIN_MILLIVOLTS;
#else
  const uint16_t compiled = 3000;
#endif
  return _battery_forward_settings.emptyMv ? _battery_forward_settings.emptyMv : compiled;
#endif
}

uint16_t CommonCLI::batteryFullMv() const {
#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
  return mesh::power::configuredFull();
#else
#ifdef BATT_MAX_MILLIVOLTS
  const uint16_t compiled = BATT_MAX_MILLIVOLTS;
#else
  const uint16_t compiled = 4200;
#endif
  return _battery_forward_settings.fullMv ? _battery_forward_settings.fullMv : compiled;
#endif
}

uint8_t CommonCLI::batteryPercent(uint16_t mv) const {
  return mesh::batteryforward::percent(mv, batteryEmptyMv(), batteryFullMv());
}

bool CommonCLI::batteryAllowsTransmit(const mesh::Packet* packet) const {
  // Explicit relay ownership survives path stripping and retry clones. Own
  // replies and OTA session traffic are not inferred from radio routing flags.
  return !packet || !packet->forwarded || batteryAllowsForward(packet->isRouteFlood());
}

bool CommonCLI::batteryAllowsForward(bool flood) const {
  // Receive/transmit admission can run before CommonCLI::loop(), including
  // the first packet after boot or a long MCU sleep. Never use a stale gate.
  loopBatteryForwarding();
  return _battery_forward_state.allows(flood);
}

void CommonCLI::loopBatteryForwarding(bool force) const {
  if (!force && !_battery_forward_settings.enabled) return;
  const uint32_t now = millis();
  if (!force && !_battery_forward_state.due(now)) return;
  const uint16_t mv = _board->getBattMilliVolts();
  _battery_forward_state.update(now, mv, batteryPercent(mv),
      mesh::batteryforward::validEndpoints(batteryEmptyMv(), batteryFullMv()),
      _battery_forward_settings);
}

bool CommonCLI::handleBatteryForwardingCommand(const char* command, char* reply) {
  if (strncmp(command, "get battery.forward", 19) == 0) {
    const char* tail = command + 19;
    while (*tail == ' ' || *tail == '\t') ++tail;
    if (!*tail) loopBatteryForwarding(true);
  }
  bool saved = false;
  const bool handled = mesh::batteryforward::handleCommand(_battery_forward_settings,
      _battery_forward_state, batteryEmptyMv(), batteryFullMv(),
#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
      true,
#else
      false,
#endif
      command, reply, 157, [this, &saved](const mesh::batteryforward::Settings& candidate) {
        return saved = saveBatteryForwarding(candidate);
      });
  if (saved) loopBatteryForwarding(true);
  return handled;
}
