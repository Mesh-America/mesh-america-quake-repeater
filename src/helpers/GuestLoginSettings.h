#pragma once

#include <helpers/IdentityStore.h>

namespace mesh {

// Stored separately so upgrading existing repeaters leaves guest access off.
class GuestLoginSettings {
  FILESYSTEM* fs_ = nullptr;
  bool enabled_ = false;
  bool healthy_ = false;

public:
  // Missing settings are a valid, unwritten default. Invalid records fail closed.
  bool begin(FILESYSTEM* fs);
  bool enabled() const { return healthy_ && enabled_; }
  bool healthy() const { return healthy_; }
  // Changes take effect only after the published record is read back.
  bool setEnabled(bool enabled);
};

}  // namespace mesh
