#pragma once

namespace mesh {
namespace detail {
struct Esp32BootAbsenceRegistry {
  const void* owner = nullptr;
  const void* context = nullptr;
  bool (*known_absent)(const void*, const char*) = nullptr;
};

inline Esp32BootAbsenceRegistry& esp32BootAbsenceRegistry() {
  static Esp32BootAbsenceRegistry registry;
  return registry;
}
}  // namespace detail

// The inventory belongs to one FS view, and is only active during synchronous
// startup. Unrelated filesystems and native positive/error probes are untouched.
inline bool esp32BootFileKnownAbsent(const void* filesystem, const char* path) {
  const detail::Esp32BootAbsenceRegistry& registry = detail::esp32BootAbsenceRegistry();
  return filesystem != nullptr && registry.owner == filesystem
      && registry.known_absent != nullptr
      && registry.known_absent(registry.context, path);
}
}  // namespace mesh
