#pragma once

#include <FS.h>

struct stat { size_t st_size = 0; };
inline int stat(const char* absolute, struct stat* info) {
  const std::string prefix = "/spiffs";
  const std::string path(absolute);
  if (!fs::stat_filesystem || path.compare(0, prefix.size(), prefix)) {
    errno = EIO;
    return -1;
  }
  const auto relative = path.substr(prefix.size());
  if (fs::stat_filesystem->fail_stat == relative) { errno = EIO; return -1; }
  const auto found = fs::stat_filesystem->files.find(relative);
  if (found == fs::stat_filesystem->files.end()) { errno = ENOENT; return -1; }
  info->st_size = found->second.size();
  return 0;
}
