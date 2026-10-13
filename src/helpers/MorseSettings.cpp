#include "MorseSettings.h"
#include "FilePresence.h"
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#include "AtomicFileWriter.h"
#elif defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
#include "ContactFileTransaction.h"
#endif

namespace mesh {
namespace {
FILESYSTEM* settings_fs = nullptr;
MorseSettings settings;
bool writes_held = false;
bool settings_usable = false;
constexpr const char* Path = "/morse_prefs";
constexpr const char* Backup = "/morse_prefs.bak";

enum class ReadResult : uint8_t { Missing, Valid, Invalid, Unreadable };

ReadResult read(const char* path, MorseSettings& result) {
  if (!settings_fs) return ReadResult::Unreadable;
  bool present = false;
  if (!filePresence(settings_fs, path, present)) return ReadResult::Unreadable;
  if (!present) return ReadResult::Missing;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*settings_fs);
  if (!file.open(path, FILE_O_READ)) return ReadResult::Unreadable;
#else
  File file = settings_fs->open(path, "r");
  if (!file) return ReadResult::Unreadable;
#endif
  uint8_t image[MorseSettingsImageSize];
  const bool right_size = file.size() == sizeof(image);
  const bool complete = right_size && file.read(image, sizeof(image)) == int(sizeof(image));
  file.close();
  if (!right_size) return ReadResult::Invalid;
  if (!complete) return ReadResult::Unreadable;
  return decodeMorseSettings(image, sizeof(image), result)
      ? ReadResult::Valid : ReadResult::Invalid;
}

bool repairBackup(const MorseSettings& candidate) {
  bool present = false;
  if (!filePresence(settings_fs, Path, present)
      || (present && !settings_fs->remove(Path))
      || !settings_fs->rename(Backup, Path)) return false;
  MorseSettings published;
  return read(Path, published) == ReadResult::Valid
      && published.frequency_khz == candidate.frequency_khz
      && published.wpm == candidate.wpm;
}

// An explicit retry may proceed after a transient I/O error has cleared.
// Never remove an unreadable committed image or retire the sole valid backup.
bool refreshWritableStore() {
  MorseSettings primary_settings, backup_settings;
  const auto primary = read(Path, primary_settings);
  if (primary == ReadResult::Unreadable) return false;
  if (primary == ReadResult::Valid) return true;
  const auto backup = read(Backup, backup_settings);
  if (backup == ReadResult::Unreadable) return false;
  return backup != ReadResult::Valid || repairBackup(backup_settings);
}
}

bool loadMorseSettings(FILESYSTEM* fs) {
  settings_fs = fs;
  settings = MorseSettings();
  writes_held = !fs;
  settings_usable = false;
  if (!fs) return false;
  MorseSettings candidate;
  const auto primary = read(Path, candidate);
  if (primary == ReadResult::Valid) {
    settings = candidate;
    settings_usable = true;
    return true;
  }
  const auto backup = read(Backup, candidate);
  writes_held = primary == ReadResult::Unreadable || backup == ReadResult::Unreadable;
  if (backup != ReadResult::Valid) {
    settings_usable = primary == ReadResult::Missing && backup == ReadResult::Missing;
    return false;
  }
  settings = candidate;
  // Keep the sole validated backup protected if its publication cannot be
  // repaired, rather than allowing the next save to retire it as stale.
  if (writes_held) return true;
  writes_held = !repairBackup(candidate);
  settings_usable = !writes_held;
  return true;
}

const MorseSettings& morseSettings() { return settings; }
bool morseSettingsUsable() { return settings_usable; }

bool saveMorseSettings(const MorseSettings& candidate) {
  if (!settings_fs || !validMorseSettings(candidate)) return false;
  if (writes_held && !refreshWritableStore()) return false;
  writes_held = false;
  uint8_t image[MorseSettingsImageSize];
  encodeMorseSettings(candidate, image);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  AtomicFileWriter writer(settings_fs, Path);
#elif defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  ContactFileTransaction writer(settings_fs, Path, filePresence<FILESYSTEM>);
#else
  return false;
#endif
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM) || defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  if (!writer || writer.write(image, sizeof(image)) != sizeof(image)
      || !writer.commit()) {
    settings_usable = false;
    writes_held = true;
    return false;
  }
  MorseSettings checked;
  if (read(Path, checked) != ReadResult::Valid
      || checked.frequency_khz != candidate.frequency_khz || checked.wpm != candidate.wpm) {
    writes_held = true;
    settings_usable = false;
    return false;
  }
  settings = candidate;
  settings_usable = true;
  return true;
#endif
}

}  // namespace mesh
