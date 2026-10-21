#pragma once

#include <helpers/IdentityStore.h>
#include <string.h>
#if defined(NRF52_PLATFORM)
#include <helpers/AtomicFileWriter.h>
#endif

namespace mesh { namespace storage {

#if defined(__GNUC__) && !defined(__clang__)
#define MESH_SETTINGS_FILE_SHARED __attribute__((noinline, noclone))
#else
#define MESH_SETTINGS_FILE_SHARED __attribute__((noinline))
#endif

// Share the filesystem boundary between small settings records. Callers keep
// their own format/version checks; no preference layout changes here.
enum class FixedSettingsRead : uint8_t { Complete, WrongSize, Unreadable };

MESH_SETTINGS_FILE_SHARED inline FixedSettingsRead readFixedSettingsFileResult(
    FILESYSTEM* fs, const char* path, uint8_t* data, size_t size) {
  if (!fs) return FixedSettingsRead::Unreadable;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*fs);
  if (!file.open(path, FILE_O_READ)) return FixedSettingsRead::Unreadable;
#else
  File file = fs->open(path, "r");
  if (!file) return FixedSettingsRead::Unreadable;
#endif
  const bool right_size = file.size() == size;
  const bool complete = right_size && file.read(data, size) == size;
  file.close();
  return !right_size ? FixedSettingsRead::WrongSize
      : complete ? FixedSettingsRead::Complete : FixedSettingsRead::Unreadable;
}

inline bool readFixedSettingsFile(
    FILESYSTEM* fs, const char* path, uint8_t* data, size_t size) {
  return readFixedSettingsFileResult(fs, path, data, size) == FixedSettingsRead::Complete;
}

#if defined(NRF52_PLATFORM)
// Reuse the existing atomic writer and compare the complete public record as
// well as its transaction checksum. Keep this uncommon path out of callers.
MESH_SETTINGS_FILE_SHARED inline AtomicFileWriter::Outcome writeCheckedSettingsFile(
    FILESYSTEM* fs, const char* path, const uint8_t* data, size_t size) {
  using Outcome = AtomicFileWriter::Outcome;
  uint8_t verified[16];
  if (!fs || !data || size == 0 || size > sizeof(verified)) return Outcome::NotCommitted;
  AtomicFileWriter file(fs, path);
  if (!file || file.write(data, size) != size) return Outcome::NotCommitted;
  if (!file.commit()) return file.outcome();
  if (!readFixedSettingsFile(fs, path, verified, size)
      || memcmp(data, verified, size) != 0) return Outcome::Indeterminate;
  return Outcome::Committed;
}
#endif

#undef MESH_SETTINGS_FILE_SHARED

}}  // namespace mesh::storage
