#pragma once

#if defined(WITH_UDP_BRIDGE)
#include <helpers/IdentityStore.h>
#include <helpers/UDPBridgePrefs.h>

namespace mesh { namespace bridge { namespace udp {

// This standalone record leaves the legacy /com_prefs binary layout intact.
class Settings {
  FILESYSTEM* fs_ = nullptr;
  Prefs prefs_;
  bool healthy_ = false;
public:
  // Missing/corrupt settings leave the transport off. A complete malformed
  // record can be replaced explicitly; I/O uncertainty requires a reload.
  bool begin(FILESYSTEM* fs);
  const Prefs& prefs() const { return prefs_; }
  bool healthy() const { return healthy_; }
  // Publish and verify first; preserve runtime preferences on failed saves.
  bool setPrefs(const Prefs& prefs);
};

}}}  // namespace mesh::bridge::udp
#endif
