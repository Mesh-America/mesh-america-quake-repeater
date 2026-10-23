#pragma once

#include <stddef.h>
#include <stdint.h>

namespace mesh { namespace companion {

// Native USB accepts bounded producer writes. Honor partial progress, and stop
// if the sink cannot accept another byte rather than spinning on a closed host.
template<typename Output>
size_t writeHelpChunks(Output& output, const char* text, size_t length) {
  if (!text) return 0;
  size_t written = 0;
  while (written < length) {
    const size_t remaining = length - written;
    const size_t chunk = remaining > 256 ? 256 : remaining;
    const size_t accepted = output.write(
        reinterpret_cast<const uint8_t*>(text) + written, chunk);
    if (accepted == 0 || accepted > chunk) break;
    written += accepted;
  }
  return written;
}

} } // namespace mesh::companion
