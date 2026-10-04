#pragma once
#include <cerrno>
#include <cstring>

struct stat {};
namespace acl_metadata {
inline std::map<std::string, unsigned> calls;
inline std::map<std::string, std::set<unsigned>> failures;
inline void reset() { calls.clear(); failures.clear(); }
}
inline int stat(const char* path, struct stat*) {
  if (!metadata_filesystem || strncmp(path, "/spiffs", 7) != 0) {
    errno = EIO;
    return -1;
  }
  const std::string name(path + 7);
  const unsigned occurrence = ++acl_metadata::calls[name];
  if (metadata_filesystem->metadata_error
      || acl_metadata::failures[name].count(occurrence)) {
    errno = EIO;
    return -1;
  }
  if (!metadata_filesystem->files.count(name)) { errno = ENOENT; return -1; }
  return 0;
}
