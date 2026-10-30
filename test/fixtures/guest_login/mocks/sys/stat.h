#pragma once
#include <GuestMemoryFS.h>
#include <cerrno>
struct stat {};
inline int stat(const char* path, struct stat*) {
  if (!guest_metadata_fs || strncmp(path, "/spiffs", 7) != 0) { errno = EIO; return -1; }
  if (guest_metadata_fs->fail_metadata) { errno = EIO; return -1; }
  const bool found = guest_metadata_fs->files.count(path + 7) != 0;
  guest_metadata_fs->record();
  if (!found) { errno = ENOENT; return -1; }
  return 0;
}
