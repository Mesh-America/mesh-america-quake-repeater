#if defined(OTA_BOOTLOADER_MIGRATION)
#include "BootloaderMigrationStore.h"

#include <helpers/AtomicFileWriter.h>
#include <helpers/FilePresence.h>
#include <helpers/PersistentStoreFormat.h>

namespace mesh { namespace ota {
namespace {
constexpr size_t RecordSize = 40;
const char* const Path = "/bl_auto";
const char* const Temp = "/bl_auto.tmp";
const uint8_t Magic[4] = {'B', 'A', 'L', 1};

bool readRecord(FILESYSTEM* fs, uint8_t record[RecordSize]) {
  File file(*fs);
  if (!file.open(Path, FILE_O_READ)) return false;
  const bool complete = !file.isDirectory() && file.size() == RecordSize
      && file.read(record, RecordSize) == static_cast<int>(RecordSize);
  file.close();
  return complete
      && memcmp(record, Magic, sizeof(Magic)) == 0
      && storage::readLE32(record + RecordSize - 4)
          == storage::updateCRC32(0xffffffffU, record, RecordSize - 4);
}
}

MigrationAutoLock bootloader_migration_auto_lock(
    FILESYSTEM* fs, const uint8_t image_hash[32]) {
  bool present = false;
  if (!fs || !image_hash || !filePresence(fs, Temp, present) || present)
    return MigrationAutoLock::Unavailable;
  if (!filePresence(fs, Path, present)) return MigrationAutoLock::Unavailable;
  if (!present) return MigrationAutoLock::Eligible;
  uint8_t record[RecordSize];
  if (!readRecord(fs, record)) return MigrationAutoLock::Unavailable;
  return memcmp(record + sizeof(Magic), image_hash, 32) == 0
      ? MigrationAutoLock::Locked : MigrationAutoLock::PreviousImage;
}

bool bootloader_migration_lock_auto(FILESYSTEM* fs, const uint8_t image_hash[32]) {
  const auto state = bootloader_migration_auto_lock(fs, image_hash);
  if (state == MigrationAutoLock::Locked) return true;
  if (state == MigrationAutoLock::Unavailable) return false;
  uint8_t record[RecordSize], verify[RecordSize];
  memcpy(record, Magic, sizeof(Magic));
  memcpy(record + sizeof(Magic), image_hash, 32);
  storage::writeLE32(record + RecordSize - 4,
      storage::updateCRC32(0xffffffffU, record, RecordSize - 4));
  AtomicFileWriter writer(fs, Path);
  return writer && writer.write(record, sizeof(record)) == sizeof(record)
      && writer.commit() && readRecord(fs, verify)
      && memcmp(record, verify, sizeof(record)) == 0;
}

} } // namespace mesh::ota
#endif
