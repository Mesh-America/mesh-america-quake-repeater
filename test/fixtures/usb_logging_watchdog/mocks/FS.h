#pragma once

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <vector>

namespace fs { class FS; }

class File {
 public:
  File() = default;
  File(fs::FS* fs, std::string path, bool writable)
      : _fs(fs), _path(std::move(path)), _writable(writable) {}
  explicit operator bool() const { return _fs != nullptr; }
  size_t size() const;
  size_t read(uint8_t* buffer, size_t count);
  size_t write(const uint8_t* buffer, size_t count);
  void flush() {}
  void close() { _fs = nullptr; }
 private:
  fs::FS* _fs = nullptr;
  std::string _path;
  size_t _offset = 0;
  bool _writable = false;
};

namespace fs {
class FS {
 public:
  std::map<std::string, std::vector<uint8_t>> files;
  std::string fail_stat, fail_open, short_read;
  std::string fail_rename_from, fail_rename_to;
  bool fail_write = false, fail_remove = false;
  bool corrupt_final_image = false, fail_final_readback = false;
  bool final_renamed = false;
  unsigned writes = 0, write_opens = 0, renames = 0, removes = 0;
  std::function<void()> after_final_rename;

  bool exists(const char* path) const { return files.count(path) != 0; }
  bool mkdir(const char*) { return true; }
  File open(const char* path, const char* mode, bool = false) {
    const bool writable = mode[0] == 'w';
    if (fail_open == path || (!writable && fail_final_readback
                             && final_renamed && std::string(path) == "/usb_wdg"))
      return {};
    if (writable) {
      ++write_opens;
      files[path].clear();
    } else if (!exists(path)) return {};
    return File(this, path, writable);
  }
  bool remove(const char* path) {
    ++removes;
    if (fail_remove) return false;
    return files.erase(path) != 0;
  }
  bool rename(const char* from, const char* to) {
    ++renames;
    if ((fail_rename_from == from && fail_rename_to == to)
        || !exists(from) || exists(to)) return false;
    files[to] = std::move(files[from]);
    files.erase(from);
    if (std::string(from) == "/usb_wdg.tmp" && std::string(to) == "/usb_wdg") {
      final_renamed = true;
      if (corrupt_final_image) files[to][0] ^= 1;
      if (after_final_rename) after_final_rename();
    }
    return true;
  }
};
inline FS* stat_filesystem = nullptr;
}  // namespace fs

inline size_t File::size() const {
  return _fs ? _fs->files.at(_path).size() : 0;
}
inline size_t File::read(uint8_t* buffer, size_t count) {
  if (!_fs || _writable) return 0;
  const auto& bytes = _fs->files.at(_path);
  size_t available = std::min(count, bytes.size() - _offset);
  if (_fs->short_read == _path && available) --available;
  std::memcpy(buffer, bytes.data() + _offset, available);
  _offset += available;
  return available;
}
inline size_t File::write(const uint8_t* buffer, size_t count) {
  if (!_fs || !_writable) return 0;
  ++_fs->writes;
  if (_fs->fail_write) return 0;
  auto& bytes = _fs->files.at(_path);
  bytes.insert(bytes.end(), buffer, buffer + count);
  return count;
}
