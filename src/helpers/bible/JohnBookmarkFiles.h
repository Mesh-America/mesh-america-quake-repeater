#pragma once
#include "JohnReader.h"

namespace mesh { namespace bible {
// A verified replacement plus one previous record also works on SPIFFS,
// whose rename does not replace an existing destination. Never truncate the
// live bookmark. A reset between the two renames is recovered from .bak.
template <typename Files>
bool loadReaderBookmark(Files& files, Position& pos) {
  uint8_t data[kBookmarkBytes];
  pos = Position{};
  if (files.read("/john.pos", data) && decodeBookmark(data, pos)) return true;
  return files.read("/john.pos.bak", data) && decodeBookmark(data, pos);
}

template <typename Files>
bool saveReaderBookmark(Files& files, Position pos) {
  if (!pos.valid()) return false;
  if (pos.atStart()) {
    // Remove the fallback before the live record so a completed clear cannot
    // resurrect an earlier place on reboot. Do not create a start marker.
    return files.remove("/john.pos.tmp") && files.remove("/john.pos.bak")
        && files.remove("/john.pos");
  }
  uint8_t data[kBookmarkBytes], verify[kBookmarkBytes];
  encodeBookmark(pos, data);
  if (!files.remove("/john.pos.tmp") || !files.write("/john.pos.tmp", data)) return false;
  if (!files.read("/john.pos.tmp", verify) || memcmp(data, verify, sizeof(data)) != 0)
    return false;
  if (files.exists("/john.pos")) {
    // Keep a valid fallback if the live record was interrupted/corrupt.
    Position old;
    // A failed read is not proof of corruption. Preserve the live record on
    // transient I/O failure rather than deleting it before publication.
    if (!files.read("/john.pos", verify)) return false;
    if (decodeBookmark(verify, old)) {
      if (!files.remove("/john.pos.bak") || !files.rename("/john.pos", "/john.pos.bak"))
        return false;
    } else if (!files.remove("/john.pos")) return false;
  }
  if (!files.rename("/john.pos.tmp", "/john.pos")) return false;
  // Retain the last valid fallback until the next successful replacement.
  return true;
}
}} // namespace mesh::bible
