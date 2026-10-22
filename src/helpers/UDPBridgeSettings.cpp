#include "UDPBridgeSettings.h"

#if defined(WITH_UDP_BRIDGE)
#include "CheckedSettingsFile.h"
#include "ContactFileTransaction.h"
#include "FilePresence.h"

namespace mesh { namespace bridge { namespace udp {
namespace { constexpr char Path[] = "/udp_bridge"; }

bool Settings::begin(FILESYSTEM* fs) {
  fs_ = fs;
  prefs_ = Prefs();
  healthy_ = false;
  if (!fs_ || !ContactFileTransaction::recover(fs_, Path, filePresence<FILESYSTEM>)) return false;
  bool present = false;
  if (!filePresence(fs_, Path, present)) return false;
  if (!present) { healthy_ = true; return true; }
  uint8_t image[PREFS_IMAGE_SIZE];
  const auto read = storage::readFixedSettingsFileResult(fs_, Path, image, sizeof(image));
  if (read == storage::FixedSettingsRead::Unreadable) return false;
  healthy_ = true;
  return read == storage::FixedSettingsRead::Complete
      && decodePrefs(image, sizeof(image), prefs_);
}

bool Settings::setPrefs(const Prefs& prefs) {
  if (!healthy_ || !fs_ || !validPrefs(prefs)) return false;
  uint8_t image[PREFS_IMAGE_SIZE];
  encodePrefs(image, prefs);
  ContactFileTransaction writer(fs_, Path, filePresence<FILESYSTEM>);
  if (!writer || writer.write(image, sizeof(image)) != sizeof(image)) {
    if (writer.outcome() == ContactFileTransaction::Outcome::Indeterminate) healthy_ = false;
    return false;
  }
  writer.commit();
  if (writer.outcome() == ContactFileTransaction::Outcome::NotCommitted) return false;
  if (writer.outcome() != ContactFileTransaction::Outcome::Committed) {
    healthy_ = false;
    return false;
  }
  uint8_t verified[PREFS_IMAGE_SIZE];
  healthy_ = storage::readFixedSettingsFile(fs_, Path, verified, sizeof(verified))
      && memcmp(image, verified, sizeof(image)) == 0;
  if (!healthy_) return false;
  prefs_ = prefs;
  return true;
}

}}}  // namespace mesh::bridge::udp
#endif
