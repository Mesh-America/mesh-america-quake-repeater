#pragma once

// SPIFFS cannot replace an existing name in one rename. Preserve the previous
// file as .bak until the verified replacement has its final name. Recovery of
// the rename gap happens before loading contacts on the next boot.
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
#include "IdentityStore.h"
#include "PersistentStoreFormat.h"
#include <stdio.h>

namespace mesh {
class ContactFileTransaction {
public:
  using PresenceProbe = bool (*)(FILESYSTEM*, const char*, bool&);
private:
  FILESYSTEM* _fs;
  const char* _target;
  char _temp[48];
  char _backup[48];
  File _file;
  File _verify;
  size_t _size = 0;
  uint32_t _crc = 0xffffffff;
  bool _ok = false;
  bool _finished = false;
  enum class CommitStage : uint8_t { Flush, Open, Verify, Publish };
  CommitStage _commit_stage = CommitStage::Flush;
  uint32_t _verify_crc = 0xffffffff;
  size_t _verify_remaining = 0;
  PresenceProbe _presence;
  static bool probe(FILESYSTEM* fs, const char* path, bool& present,
                    PresenceProbe presence) {
    if (presence) return presence(fs, path, present);
    present = fs->exists(path);
    return true;
  }
public:
  enum class CommitProgress : uint8_t { Pending, Succeeded, Failed };
  static bool recover(FILESYSTEM* fs, const char* target,
                      PresenceProbe presence = nullptr) {
    char backup[48];
    snprintf(backup, sizeof(backup), "%s.bak", target);
    bool target_exists = false, backup_exists = false;
    if (!probe(fs, target, target_exists, presence)
        || !probe(fs, backup, backup_exists, presence)) return false;
    if (target_exists) return true;
    return !backup_exists || fs->rename(backup, target);
  }
  ContactFileTransaction(FILESYSTEM* fs, const char* target,
                         PresenceProbe presence = nullptr)
      : _fs(fs), _target(target), _presence(presence) {
    snprintf(_temp, sizeof(_temp), "%s.tmp", target);
    snprintf(_backup, sizeof(_backup), "%s.bak", target);
    if (!recover(fs, target, presence)) return;
    if (fs->exists(_temp) && !fs->remove(_temp)) return;
#if defined(RP2040_PLATFORM)
    _file = fs->open(_temp, "w");
#else
    _file = fs->open(_temp, "w", true);
#endif
    _ok = static_cast<bool>(_file);
  }
  ~ContactFileTransaction() {
    if (_file) _file.close();
    if (_verify) _verify.close();
    if (!_finished) _fs->remove(_temp);
  }
  operator bool() const { return _ok; }
  bool readyToPublish() const {
    return !_finished && _commit_stage == CommitStage::Publish;
  }
  size_t write(const uint8_t* data, size_t len) {
    if (!_ok || _finished || _commit_stage != CommitStage::Flush) return 0;
    const size_t wrote = _file.write(data, len);
    _ok = wrote == len;
    _size += wrote;
    _crc = storage::updateCRC32(_crc, data, wrote);
    return wrote;
  }
  // Each verification pass reads at most one small chunk. The caller can
  // service its transports between passes without exposing the rename gap.
  // A synchronous durability operation uses commit() to drain the same steps.
  CommitProgress serviceCommit(bool valid = true) {
    if (_finished) return CommitProgress::Failed;
    bool ok = _ok && valid;
    if (ok && _commit_stage == CommitStage::Flush) {
      if (_file) { _file.flush(); _file.close(); }
      _commit_stage = CommitStage::Open;
      return CommitProgress::Pending;
    }
    if (ok && _commit_stage == CommitStage::Open) {
      _verify = _fs->open(_temp, "r");
      ok = _verify && _verify.size() == _size;
      if (ok) {
        _verify_remaining = _size;
        _commit_stage = CommitStage::Verify;
        return CommitProgress::Pending;
      }
    }
    if (ok && _commit_stage == CommitStage::Verify) {
      uint8_t buf[64];
      const size_t count = _verify_remaining < sizeof(buf)
          ? _verify_remaining : sizeof(buf);
      if (count != 0) {
        ok = _verify.read(buf, count) == count;
        if (ok) {
          _verify_crc = storage::updateCRC32(_verify_crc, buf, count);
          _verify_remaining -= count;
          return CommitProgress::Pending;
        }
      } else {
        _verify.close();
        ok = _verify_crc == _crc;
        if (ok) {
          _commit_stage = CommitStage::Publish;
          return CommitProgress::Pending;
        }
      }
    }
    // Keep both renames and any rollback in this pass. Cold-path readers must
    // not run between removing the target name and installing its replacement.
    if (_file) _file.close();
    if (_verify) _verify.close();
    bool backup_exists = false, target_exists = false;
    if (ok) ok = probe(_fs, _backup, backup_exists, _presence)
        && probe(_fs, _target, target_exists, _presence);
    if (ok && backup_exists) ok = _fs->remove(_backup);
    bool backed_up = false;
    if (ok && target_exists) {
      ok = _fs->rename(_target, _backup);
      backed_up = ok;
    }
    if (ok) ok = _fs->rename(_temp, _target);
    if (!ok && backed_up) _fs->rename(_backup, _target);
    if (ok) _fs->remove(_backup);
    else _fs->remove(_temp);
    _finished = true;
    return ok ? CommitProgress::Succeeded : CommitProgress::Failed;
  }
  bool commit(bool valid = true) {
    CommitProgress progress;
    do { progress = serviceCommit(valid); }
    while (progress == CommitProgress::Pending);
    return progress == CommitProgress::Succeeded;
  }
};
} // namespace mesh
#endif
