#pragma once

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <string>
#include <vector>
#include <Arduino.h>
enum { FILE_O_READ = 0, FILE_O_WRITE = 1 };

class FakeFilesystem;
class File {
  FakeFilesystem* _fs = nullptr;
  std::string _path;
  size_t _position = 0;
  bool _write = false;
  unsigned _read_generation = 0;
  std::vector<uint8_t> _read_inode;
public:
  File() = default;
  explicit File(FakeFilesystem& fs) : _fs(&fs) {}
  File(FakeFilesystem* fs, const char* path, bool write);
  bool open(const char* path, uint8_t mode);
  explicit operator bool() const { return _fs != nullptr; }
  size_t read(uint8_t* bytes, size_t length);
  size_t write(const uint8_t* bytes, size_t length);
  size_t size() const;
  bool seek(size_t position);
  void flush() {}
  void close() { _fs = nullptr; }
};

class FakeFilesystem {
  struct Config { uint32_t block_count = 256, block_size = 4096; } _config;
  struct Lfs { const Config* cfg; } _lfs{&_config};
public:
  using Files = std::map<std::string, std::vector<uint8_t>>;
  Files files;
  size_t capacity = 1024 * 1024;
  size_t max_write = std::numeric_limits<size_t>::max();
  size_t largest_read = 0, largest_write = 0;
  std::string fail_read;
  bool metadata_error = false, fail_create = false, fail_remove = false;
  unsigned removes = 0, missing_remove_logs = 0;
  unsigned fail_rename = 0, renames = 0, writes = 0, reads = 0, opens = 0;
  std::vector<Files> rename_snapshots;
  std::map<std::string, unsigned> generations;
  bool exists(const char* path) const { return files.count(path) != 0; }
  bool mkdir(const char*) { return true; }
  bool remove(const char* path) {
    ++removes;
    if (!exists(path)) { ++missing_remove_logs; return false; }
    if (fail_remove) return false;
    ++generations[path];
    return files.erase(path) != 0;
  }
  File open(const char* path, const char* mode = "r", bool = false) {
    ++opens;
    if (*mode != 'r') {
      if (fail_create) return File();
      files[path].clear();
      return File(this, path, true);
    }
    if (fail_read == path || !exists(path)) return File();
    return File(this, path, false);
  }
  bool rename(const char* from, const char* to) {
    ++renames;
    if (renames == fail_rename || !exists(from)) return false;
#if defined(ESP32_PLATFORM)
    if (exists(to)) return false;
#endif
    files[to] = files.at(from);
    files.erase(from);
    ++generations[from]; ++generations[to];
    rename_snapshots.push_back(files);
    return true;
  }
  size_t totalBytes() const { return capacity; }
  void setBlockCount(uint32_t count) { _config.block_count = count; }
  Lfs* _getFS() { _lfs.cfg = &_config; return &_lfs; }
  size_t usedBytes() const {
    size_t total = 0;
    for (const auto& f : files) total += f.second.size();
    return total;
  }
} SPIFFS;

int _getLfsUsedBlockCount(FakeFilesystem* fs) {
  unsigned used = 2; // directory metadata pair
  for (const auto& file : fs->files) used += (file.second.size() + 4095) / 4096;
  return used;
}

File::File(FakeFilesystem* fs, const char* path, bool write)
    : _fs(fs), _path(path), _write(write) {
  if (!write) {
    _read_generation = fs->generations[path];
    _read_inode = fs->files.at(path);
  }
}
bool File::open(const char* path, uint8_t mode) {
  if (!_fs) return false;
  *this = _fs->open(path, mode == FILE_O_WRITE ? "w" : "r");
  return static_cast<bool>(*this);
}
size_t File::read(uint8_t* bytes, size_t length) {
  if (!_fs || _write || _fs->fail_read == _path) return 0;
  ++_fs->reads;
  _fs->largest_read = std::max(_fs->largest_read, length);
  // An open file keeps its old inode across a rename/unlink. A later File
  // opened on the same name observes the replacement, as SPIFFS/POSIX do.
  auto& data = _fs->generations[_path] == _read_generation
      ? _fs->files.at(_path) : _read_inode;
  const size_t count = std::min(length, data.size() - std::min(data.size(), _position));
  if (count) memcpy(bytes, data.data() + _position, count);
  _position += count;
  return count;
}
size_t File::write(const uint8_t* bytes, size_t length) {
  if (!_fs || !_write) return 0;
  ++_fs->writes;
  _fs->largest_write = std::max(_fs->largest_write, length);
  const size_t count = std::min(length, _fs->max_write);
  auto& data = _fs->files[_path];
  data.resize(_position + count);
  memcpy(data.data() + _position, bytes, count);
  _position += count;
  return count;
}
size_t File::size() const {
  if (!_fs) return 0;
  return !_write && _fs->generations[_path] != _read_generation
      ? _read_inode.size() : _fs->files.at(_path).size();
}
bool File::seek(size_t pos) {
  if (!_fs || pos > size()) return false;
  _position = pos;
  return true;
}
