#include "ESP32RadioTrace.h"

#if MESH_RADIO_TRACE_ENABLED
#include <esp_timer.h>
#include <Utils.h>

namespace mesh {
namespace radiotrace {

Trace& trace() {
  static Trace value;
  return value;
}

uint64_t nowUs() { return static_cast<uint64_t>(esp_timer_get_time()); }

uint64_t fingerprint(const uint8_t* bytes, size_t length) {
  uint8_t hash[8];
  mesh::Utils::sha256(hash, sizeof(hash), bytes, static_cast<int>(length));
  // The schema is an integer rendered as 16 hex digits, independent of host
  // endianness. It hashes complete wire bytes, including the route header.
  uint64_t result = 0;
  for (uint8_t value : hash) result = (result << 8) | value;
  return result;
}

}  // namespace radiotrace
}  // namespace mesh
#endif
