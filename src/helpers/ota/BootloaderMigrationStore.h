#pragma once

#if defined(OTA_BOOTLOADER_MIGRATION)
#include <helpers/IdentityStore.h>

namespace mesh { namespace ota {

enum class MigrationAutoLock : uint8_t { Eligible, PreviousImage, Locked, Unavailable };

// image_hash is SHA-256 of the complete, verified running application. Pass
// nullptr as the filesystem when the role is using volatile fallback storage.
MigrationAutoLock bootloader_migration_auto_lock(
    FILESYSTEM* fs, const uint8_t image_hash[32]);

// Record an attempt before inspecting the bootloader. A matching durable record is
// already sufficient; a different image may atomically replace its predecessor.
bool bootloader_migration_lock_auto(FILESYSTEM* fs, const uint8_t image_hash[32]);

} } // namespace mesh::ota
#endif
