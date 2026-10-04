#pragma once

#if defined(ESP32_PLATFORM)
#include "FilePresence.h"
#endif

namespace mesh {

static const char CLIENT_ACL_PRIMARY_PATH[] = "/s_contacts";
static const char CLIENT_ACL_TEMP_PATH[] = "/s_contacts.tmp";
static const char CLIENT_ACL_BACKUP_PATH[] = "/s_contacts.bak";

// ESP ACL stores are mounted at /spiffs. Unlike FS::exists(), the metadata
// probe does not open/close the file and distinguishes absent from unreadable.
template <typename Filesystem>
bool clientACLFilePresence(Filesystem* fs, const char* path, bool& present) {
#if defined(ESP32_PLATFORM)
  return filePresence(fs, path, present);
#else
  present = fs->exists(path);
  return true;
#endif
}

enum class ClientACLFileValidation { Invalid, Valid, MetadataError };

inline ClientACLFileValidation clientACLValidation(bool valid) {
  return valid ? ClientACLFileValidation::Valid
               : ClientACLFileValidation::Invalid;
}
inline ClientACLFileValidation clientACLValidation(ClientACLFileValidation valid) {
  return valid;
}

template <typename Filesystem>
bool removeClientACLArtifact(Filesystem* fs, const char* path) {
  bool present;
  if (!clientACLFilePresence(fs, path, present)) return false;
  if (!present) return true;
  fs->remove(path);
  return clientACLFilePresence(fs, path, present) && !present;
}

// Recover the last published image after any power-loss boundary in the
// temp -> backup -> primary transaction. A present primary is authoritative;
// if publication had not completed, the backup is restored instead.
template <typename Filesystem>
bool recoverClientACLFiles(Filesystem* fs) {
  bool primary_exists, backup_exists;
  if (!clientACLFilePresence(fs, CLIENT_ACL_PRIMARY_PATH, primary_exists)) return false;
  if (primary_exists) {
    // The primary is already authoritative.  Cleanup is best-effort: a
    // filesystem which cannot remove a stale artifact must not make the
    // committed image appear unavailable.
    removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
    removeClientACLArtifact(fs, CLIENT_ACL_BACKUP_PATH);
    return true;
  }
  if (!clientACLFilePresence(fs, CLIENT_ACL_BACKUP_PATH, backup_exists)) return false;
  if (backup_exists) {
    if (!fs->rename(CLIENT_ACL_BACKUP_PATH, CLIENT_ACL_PRIMARY_PATH)) {
      return false;
    }
    removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
    return true;
  }
  return removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
}

template <typename Filesystem, typename Validator>
bool recoverClientACLFilesVerified(Filesystem* fs, Validator is_valid) {
  bool primary_exists, backup_exists;
  if (!clientACLFilePresence(fs, CLIENT_ACL_PRIMARY_PATH, primary_exists)) return false;
  if (primary_exists) {
    const auto result = clientACLValidation(is_valid(fs, CLIENT_ACL_PRIMARY_PATH));
    if (result == ClientACLFileValidation::MetadataError) return false;
    if (result == ClientACLFileValidation::Valid) {
      // A validated primary remains authoritative even when stale-artifact
      // cleanup is temporarily unavailable.
      removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
      removeClientACLArtifact(fs, CLIENT_ACL_BACKUP_PATH);
      return true;
    }
  }
  if (!clientACLFilePresence(fs, CLIENT_ACL_BACKUP_PATH, backup_exists)) return false;
  if (backup_exists) {
    const auto result = clientACLValidation(is_valid(fs, CLIENT_ACL_BACKUP_PATH));
    if (result == ClientACLFileValidation::MetadataError) return false;
    if (result == ClientACLFileValidation::Valid) {
      if (!removeClientACLArtifact(fs, CLIENT_ACL_PRIMARY_PATH)
          || !fs->rename(CLIENT_ACL_BACKUP_PATH, CLIENT_ACL_PRIMARY_PATH)) {
        return false;
      }
      removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
      return true;
    }
  }
  return !primary_exists && !backup_exists
      && removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
}

template <typename Filesystem>
bool publishVerifiedClientACLTemp(Filesystem* fs, bool temp_verified) {
  if (!temp_verified) {
    removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
    return false;
  }
  bool backup_exists, had_primary;
  if (!clientACLFilePresence(fs, CLIENT_ACL_BACKUP_PATH, backup_exists)
      || backup_exists
      || !clientACLFilePresence(fs, CLIENT_ACL_PRIMARY_PATH, had_primary)) return false;

  if (had_primary
      && !fs->rename(CLIENT_ACL_PRIMARY_PATH, CLIENT_ACL_BACKUP_PATH)) {
    return false;
  }
  if (!fs->rename(CLIENT_ACL_TEMP_PATH, CLIENT_ACL_PRIMARY_PATH)) {
    // Restore the last committed image immediately when possible. If this
    // rename also fails, leave both artifacts for recoverClientACLFiles().
    bool primary_exists;
    if (had_primary && clientACLFilePresence(fs, CLIENT_ACL_PRIMARY_PATH, primary_exists)
        && !primary_exists) {
      fs->rename(CLIENT_ACL_BACKUP_PATH, CLIENT_ACL_PRIMARY_PATH);
    }
    return false;
  }

  // A stale backup does not make the newly published primary unsuccessful;
  // recovery removes it before the next load/save.
  removeClientACLArtifact(fs, CLIENT_ACL_BACKUP_PATH);
  return true;
}

template <typename Filesystem, typename Validator>
bool publishVerifiedClientACLTemp(Filesystem* fs, bool temp_verified,
                                  Validator is_valid) {
  if (!temp_verified) {
    removeClientACLArtifact(fs, CLIENT_ACL_TEMP_PATH);
    return false;
  }
  bool backup_exists, had_primary;
  if (!clientACLFilePresence(fs, CLIENT_ACL_BACKUP_PATH, backup_exists)
      || backup_exists
      || !clientACLFilePresence(fs, CLIENT_ACL_PRIMARY_PATH, had_primary)) return false;
  if (had_primary
      && !fs->rename(CLIENT_ACL_PRIMARY_PATH, CLIENT_ACL_BACKUP_PATH)) {
    return false;
  }
  if (!fs->rename(CLIENT_ACL_TEMP_PATH, CLIENT_ACL_PRIMARY_PATH)
      || clientACLValidation(is_valid(fs, CLIENT_ACL_PRIMARY_PATH))
          != ClientACLFileValidation::Valid) {
    if (removeClientACLArtifact(fs, CLIENT_ACL_PRIMARY_PATH) && had_primary) {
      fs->rename(CLIENT_ACL_BACKUP_PATH, CLIENT_ACL_PRIMARY_PATH);
    }
    return false;
  }
  // Publication committed at the successful temp -> primary rename and
  // validation.  A stale backup is recoverable housekeeping, not a failed
  // save (which could otherwise make RAM roll back while disk holds new data).
  removeClientACLArtifact(fs, CLIENT_ACL_BACKUP_PATH);
  return true;
}

} // namespace mesh
