#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

class GuestMemoryFS;
inline GuestMemoryFS* guest_metadata_fs = nullptr;
using GuestFiles = std::map<std::string, std::vector<uint8_t>>;
enum { FILE_O_READ = 1, FILE_O_WRITE = 2 };
class File {
  GuestMemoryFS* owner_ = nullptr;
  std::string path_;
  size_t cursor_ = 0;
  bool opened_ = false;
public:
  File() = default;
  explicit File(GuestMemoryFS& fs) : owner_(&fs) {}
  File(GuestMemoryFS* fs, const char* path, bool opened) : owner_(fs), path_(path), opened_(opened) {}
  bool open(const char*, int);
  explicit operator bool() const { return opened_; }
  bool isDirectory() const { return false; }
  size_t size() const;
  size_t read(uint8_t*, size_t);
  size_t write(const uint8_t*, size_t);
  bool setBufferSize(size_t) { return true; }
  void flush();
  void close();
};

class GuestMemoryFS {
public:
  GuestFiles files;
  std::vector<GuestFiles> snapshots;
  bool capture = false, fail_metadata = false, fail_open_write = false;
  bool fail_stage_open = false, fail_stage_read = false, corrupt_stage = false;
  bool fail_public_read = false, published = false;
  bool fail_remove_temp = false, fail_remove_backup = false;
  bool fail_backup = false, fail_publish = false, false_publish = false, late_error = false;
  int short_write = -1;
  unsigned writes = 0;
  GuestMemoryFS() { guest_metadata_fs = this; }
  bool mkdir(const char*) { return true; }
  void record() { if (capture) snapshots.push_back(files); }
  void _lockFS() {} void _unlockFS() {} GuestMemoryFS* _getFS() { return this; }
  bool exists(const char* path) { const bool yes = files.count(path); record(); return yes; }
  bool remove(const char* path) {
    const bool fail = (fail_remove_temp && !strcmp(path, "/guest_login.tmp"))
        || (fail_remove_backup && !strcmp(path, "/guest_login.bak"));
    const bool removed = !fail && files.erase(path); record(); return removed;
  }
  bool rename(const char* from, const char* to) {
    const bool is_publish = !strcmp(from, "/guest_login.tmp");
    if ((fail_backup && !strcmp(from, "/guest_login")) || (fail_publish && is_publish)
        || !files.count(from)) { record(); return false; }
#if defined(ESP32_PLATFORM)
    if (files.count(to)) { record(); return false; }
#endif
    if (!(false_publish && is_publish)) {
      files[to] = files.at(from); files.erase(from);
      if (is_publish) published = true;
    }
    record();
    return !(late_error && is_publish);
  }
  File open(const char* path, const char* mode = "r", bool = false) {
    if (!path) return {};
    if (*mode == 'w') {
      if (fail_open_write) { record(); return {}; }
      files[path].clear();
    } else if (fail_stage_open && !strcmp(path, "/guest_login.tmp")) {
      record(); return {};
    }
    const bool found = files.count(path); record(); return File(this, path, found);
  }
};
inline bool File::open(const char* path, int mode) {
  if (!owner_) return false;
  *this = owner_->open(path, mode == FILE_O_WRITE ? "w" : "r");
  return opened_;
}
inline size_t File::size() const { return opened_ ? owner_->files.at(path_).size() : 0; }
inline size_t File::read(uint8_t* bytes, size_t count) {
  if (!opened_ || (owner_->fail_stage_read && path_ == "/guest_login.tmp")
      || (owner_->fail_public_read && owner_->published && path_ == "/guest_login")) {
    if (owner_) owner_->record(); return 0;
  }
  const auto& image = owner_->files.at(path_);
  count = std::min(count, image.size() - cursor_);
  memcpy(bytes, image.data() + cursor_, count); cursor_ += count; owner_->record(); return count;
}
inline size_t File::write(const uint8_t* bytes, size_t count) {
  if (!opened_) return 0;
  ++owner_->writes;
  if (owner_->short_write >= 0) count = std::min(count, size_t(owner_->short_write));
  auto& image = owner_->files[path_]; image.insert(image.end(), bytes, bytes + count);
  if (owner_->corrupt_stage && !image.empty()) image[0] ^= 1;
  owner_->record(); return count;
}
inline void File::flush() { if (owner_) owner_->record(); }
inline void File::close() { opened_ = false; if (owner_) owner_->record(); }
constexpr int LFS_ERR_NOENT = -2;
struct lfs_info {};
inline int lfs_stat(GuestMemoryFS* fs, const char* path, lfs_info*) {
  if (fs->fail_metadata) return -5;
  const bool found = fs->files.count(path); fs->record(); return found ? 0 : LFS_ERR_NOENT;
}
