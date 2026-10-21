#if defined(OLED_AUTO_DETECT) && OLED_AUTO_DETECT

#include "OLEDControllerSettings.h"
#include <helpers/CheckedSettingsFile.h>

#include <stdio.h>
#include <string.h>

namespace mesh { namespace ui {
namespace {
FILESYSTEM* settings_fs = nullptr;
OLEDControllerMode active_mode = defaultOLEDControllerMode();
OLEDControllerMode configured_mode = defaultOLEDControllerMode();
bool saved_mode = false;
bool recovery_pending = false;
const char* const path = "/display_controller";
const char* const backup = "/display_controller.bak";
#if !defined(NRF52_PLATFORM)
const char* const temporary = "/display_controller.tmp";
#endif

const char* modeName(OLEDControllerMode mode) {
  switch (mode) {
    case OLEDControllerMode::SSD1306: return "ssd1306";
    case OLEDControllerMode::SH1106: return "sh1106";
    default: return "auto";
  }
}

const uint8_t images[3][6] = {
    {'O', 'C', 1, 0, 0, 'O' ^ 'C' ^ 1},
    {'O', 'C', 1, 1, 0, 'O' ^ 'C' ^ 1 ^ 1},
    {'O', 'C', 1, 2, 0, 'O' ^ 'C' ^ 1 ^ 2}};

bool readPrefs(const char* name, OLEDControllerMode& mode) {
  uint8_t data[sizeof(images[0])];
  if (!storage::readFixedSettingsFile(settings_fs, name, data, sizeof(data))
      || data[3] > uint8_t(OLEDControllerMode::SH1106)
      || memcmp(data, images[data[3]], sizeof(data)) != 0) return false;
  mode = OLEDControllerMode(data[3]);
  return true;
}

bool savePrefs(OLEDControllerMode mode) {
  // A failed backup recovery may leave that backup as the only valid record.
  // Do not rotate it away until a later successful load repairs the store.
  if (!settings_fs || recovery_pending) return false;
  const uint8_t* data = images[uint8_t(mode)];
#if defined(NRF52_PLATFORM)
  // Share the existing LittleFS transaction implementation on constrained
  // nRF52 targets: it verifies staged bytes and the published file by CRC32C.
  const auto outcome = storage::writeCheckedSettingsFile(
      settings_fs, path, data, sizeof(images[0]));
  if (outcome != mesh::AtomicFileWriter::Outcome::Committed) {
    recovery_pending = outcome == mesh::AtomicFileWriter::Outcome::Indeterminate;
    return false;
  }
  settings_fs->remove(backup);
  return true;
#else
  // Keep the previous complete record until the replacement is read back.
  settings_fs->remove(temporary);
  if (settings_fs->exists(temporary)) return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*settings_fs);
  if (!file.open(temporary, FILE_O_WRITE)) return false;
#elif defined(RP2040_PLATFORM)
  File file = settings_fs->open(temporary, "w");
  if (!file) return false;
#else
  File file = settings_fs->open(temporary, "w", true);
  if (!file) return false;
#endif
  const bool written = file.write(data, sizeof(images[0])) == sizeof(images[0]);
  file.close();
  OLEDControllerMode checked = OLEDControllerMode::Auto;
  if (!written || !readPrefs(temporary, checked) || checked != mode) return false;
  if (settings_fs->exists(backup) && !settings_fs->remove(backup)) return false;
  if (settings_fs->exists(path) && !settings_fs->rename(path, backup)) return false;
  if (!settings_fs->rename(temporary, path)) {
    if (settings_fs->exists(backup) && !settings_fs->rename(backup, path)) {
      recovery_pending = true;
    }
    return false;
  }
  settings_fs->remove(backup);
  return true;
#endif
}

bool equalMode(const char* value, const char* expected) {
  while (*value && *expected) {
    const char c = *value >= 'A' && *value <= 'Z' ? *value + ('a' - 'A') : *value;
    if (c != *expected) return false;
    ++value;
    ++expected;
  }
  return *value == 0 && *expected == 0;
}
}

bool loadOLEDControllerSettings(FILESYSTEM* fs) {
  settings_fs = fs;
  active_mode = configured_mode = defaultOLEDControllerMode();
  saved_mode = recovery_pending = false;
  if (!fs) return false;
  OLEDControllerMode loaded = defaultOLEDControllerMode();
  bool found = readPrefs(path, loaded);
  if (!found && readPrefs(backup, loaded)) {
    found = true;
    recovery_pending = (fs->exists(path) && !fs->remove(path))
        || !fs->rename(backup, path);
  }
  if (found) {
    active_mode = configured_mode = loaded;
    saved_mode = true;
  }
  return found;
}

OLEDControllerMode oledControllerMode() { return active_mode; }

bool handleOLEDControllerCommand(const char* command, char* reply,
                                 size_t reply_size, bool supported) {
  const bool get = strncmp(command, "get ", 4) == 0;
  const bool set = strncmp(command, "set ", 4) == 0;
  if (!get && !set) return false;
  const char* key = command + 4;
  constexpr size_t key_length = sizeof("display.controller") - 1;
  if (strncmp(key, "display.controller", key_length) != 0
      || (key[key_length] != 0 && key[key_length] != ' ')) return false;
  if (!supported) {
    snprintf(reply, reply_size, "Error: display controller unsupported");
    return true;
  }
  const char* value = key + key_length;
  if (get) {
    if (*value) snprintf(reply, reply_size, "Error: unexpected argument");
    else snprintf(reply, reply_size, "display.controller %s (active %s%s)",
                  modeName(configured_mode), modeName(active_mode),
                  configured_mode != active_mode ? "; restart required" : "");
    return true;
  }
  while (*value == ' ') ++value;
  OLEDControllerMode candidate;
  if (equalMode(value, "auto")) candidate = OLEDControllerMode::Auto;
  else if (equalMode(value, "ssd1306")) candidate = OLEDControllerMode::SSD1306;
  else if (equalMode(value, "sh1106")) candidate = OLEDControllerMode::SH1106;
  else {
    snprintf(reply, reply_size, "Error: use set display.controller <auto|ssd1306|sh1106>");
    return true;
  }
  if ((!saved_mode || candidate != configured_mode) && !savePrefs(candidate)) {
    snprintf(reply, reply_size, "Error: display controller save failed");
    return true;
  }
  configured_mode = candidate;
  saved_mode = true;
  snprintf(reply, reply_size, "OK - display controller %s%s", modeName(candidate),
            configured_mode != active_mode ? "; restart required" : "");
  return true;
}

}}  // namespace mesh::ui

#endif  // OLED_AUTO_DETECT
