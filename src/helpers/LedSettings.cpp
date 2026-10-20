#include "LedSettings.h"
#include <MeshCore.h>
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#include <helpers/AtomicFileWriter.h>
#else
#include <helpers/ContactFileTransaction.h>
#endif
#include <stdio.h>
#include <string.h>

namespace mesh { namespace leds {
namespace {
MainBoard* main_board = nullptr;
FILESYSTEM* settings_fs = nullptr;
const char* const path = "/leds_v1";
const char* const backup = "/leds_v1.bak";

void encode(bool on, uint8_t (&data)[8]) {
  const uint8_t value = on ? 1 : 0;
  const uint8_t image[] = {'L', 'E', 'D', 1, value,
                          static_cast<uint8_t>(value ^ 0xff), 0, 0};
  memcpy(data, image, sizeof(data));
}

bool readSetting(const char* name, bool& on) {
  if (!settings_fs) return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*settings_fs);
  if (!file.open(name, FILE_O_READ)) return false;
#else
  File file = settings_fs->open(name, "r");
  if (!file) return false;
#endif
  uint8_t data[8], expected[8];
  const bool complete = file.size() == sizeof(data)
      && file.read(data, sizeof(data)) == sizeof(data);
  file.close();
  if (!complete || data[4] > 1) return false;
  encode(data[4] != 0, expected);
  if (memcmp(data, expected, sizeof(data)) != 0) return false;
  on = data[4] != 0;
  return true;
}

bool saveSetting(bool on) {
  if (!settings_fs) return false;
  uint8_t data[8];
  encode(on, data);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  AtomicFileWriter file(settings_fs, path);
#else
  ContactFileTransaction file(settings_fs, path);
#endif
  if (!file || file.write(data, sizeof(data)) != sizeof(data) || !file.commit())
    return false;
  bool checked = !on;
  return readSetting(path, checked) && checked == on;
}
} // namespace

void beginSettings(MainBoard& board, FILESYSTEM* fs) {
  main_board = &board;
  settings_fs = fs;
  bool on = true;
  if (!readSetting(path, on) && readSetting(backup, on)) {
    // Recover the rename gap without discarding the last complete preference.
    if ((!fs->exists(path) || fs->remove(path)) && fs->rename(backup, path)) {
      bool checked = !on;
      if (!readSetting(path, checked) || checked != on) settings_fs = nullptr;
    } else {
      settings_fs = nullptr;
    }
  }
  setEnabled(on);
  board.applyLedPolicy();
  applyStatusPolicy();
}

bool handleCommand(const char* command, char* reply, size_t capacity) {
  if (!command || !reply || capacity == 0) return false;
  const bool get = strncmp(command, "get ", 4) == 0;
  const bool set = strncmp(command, "set ", 4) == 0;
  if ((!get && !set) || strncmp(command + 4, "leds", 4) != 0) return false;
  const char* value = command + 8;
  if (*value && *value != ' ' && *value != '\t') return false;
  if (get) {
    if (*value) snprintf(reply, capacity, "Error: usage get leds");
    else snprintf(reply, capacity, "> %s", enabled() ? "on" : "off");
    return true;
  }
  while (*value == ' ' || *value == '\t') ++value;
  if (strcmp(value, "on") != 0 && strcmp(value, "off") != 0) {
    snprintf(reply, capacity, "Error: usage set leds on|off");
    return true;
  }
  const bool on = strcmp(value, "on") == 0;
  if (!main_board || !saveSetting(on)) {
    snprintf(reply, capacity, "Error: LED setting save unconfirmed; reboot may differ");
    return true;
  }
  setEnabled(on);
  main_board->applyLedPolicy();
  applyStatusPolicy();
  snprintf(reply, capacity, "OK");
  return true;
}
} } // namespace mesh::leds
