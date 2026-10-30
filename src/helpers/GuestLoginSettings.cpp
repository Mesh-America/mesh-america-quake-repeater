#include "GuestLoginSettings.h"
#include "CheckedSettingsFile.h"
#include "FilePresence.h"
#include "PersistentStoreFormat.h"
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#include "AtomicFileWriter.h"
#else
#include "ContactFileTransaction.h"
#endif

namespace mesh {
namespace {
constexpr char Path[] = "/guest_login";
constexpr size_t ImageSize = 12;

void encode(uint8_t (&image)[ImageSize], bool enabled) {
  memset(image, 0, sizeof(image));
  memcpy(image, "GLG1", 4);
  image[4] = uint8_t(enabled);
  storage::writeLE32(image + 8, storage::updateCRC32(0xffffffff, image, 8));
}

bool valid(const uint8_t (&image)[ImageSize]) {
  return memcmp(image, "GLG1", 4) == 0 && image[4] <= 1
      && image[5] == 0 && image[6] == 0 && image[7] == 0
      && storage::readLE32(image + 8)
          == storage::updateCRC32(0xffffffff, image, 8);
}
}

bool GuestLoginSettings::begin(FILESYSTEM* fs) {
  fs_ = fs;
  enabled_ = false;
  healthy_ = false;
  if (!fs_) return false;
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  if (!ContactFileTransaction::recover(fs_, Path, filePresence<FILESYSTEM>)) return false;
#endif
  bool present = false;
  if (!filePresence(fs_, Path, present)) return false;
  if (!present) {
    healthy_ = true;
    return true;
  }
  uint8_t image[ImageSize];
  const auto result = storage::readFixedSettingsFileResult(fs_, Path, image, sizeof(image));
  if (result == storage::FixedSettingsRead::Unreadable) return false;
  // An explicit administrator setting may replace a complete malformed record;
  // an I/O error must first be reconciled by a successful reload.
  healthy_ = true;
  if (result != storage::FixedSettingsRead::Complete || !valid(image)) return false;
  enabled_ = image[4] != 0;
  return true;
}

bool GuestLoginSettings::setEnabled(bool enabled) {
  if (!healthy_ || !fs_) return false;
  uint8_t image[ImageSize];
  encode(image, enabled);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  AtomicFileWriter writer(fs_, Path);
  const bool wrote = writer && writer.write(image, sizeof(image)) == sizeof(image);
  const bool saved = writer.commit(wrote);
  if (writer.outcome() == AtomicFileWriter::Outcome::Indeterminate) healthy_ = false;
  if (!saved) return false;
#else
  ContactFileTransaction writer(fs_, Path, filePresence<FILESYSTEM>);
  if (!writer || writer.write(image, sizeof(image)) != sizeof(image)) {
    if (writer.outcome() == ContactFileTransaction::Outcome::Indeterminate) healthy_ = false;
    return false;
  }
  writer.commit();
  if (writer.outcome() == ContactFileTransaction::Outcome::NotCommitted) return false;
#endif
  uint8_t verified[ImageSize];
  healthy_ = storage::readFixedSettingsFile(fs_, Path, verified, sizeof(verified))
      && memcmp(image, verified, sizeof(image)) == 0;
  if (!healthy_) return false;
  enabled_ = enabled;
  return true;
}

}  // namespace mesh
