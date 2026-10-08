#include "UsbLoggingClientActivity.h"

#if defined(ARDUINO)
#include <Arduino.h>
#include "UsbLogging.h"
#if MESH_USB_CONSOLE_COOPERATIVE
#include <atomic>

namespace mesh {
namespace {
std::atomic<uint32_t> session_generation{1};
std::atomic<uint32_t> stats_generation{0};
std::atomic<uint32_t> stats_deadline{0};
}

void noteUsbLoggingStatsCommand(const char* command) {
  if (!isUsbLoggingStatsCommand(command)) return;
  const uint32_t generation = session_generation.load(std::memory_order_acquire);
  uint32_t deadline = millis() + USB_LOGGING_CLIENT_LEASE_MS;
  if (!deadline) deadline = UINT32_MAX;  // Reserve zero; at most 1 ms early.
  stats_deadline.store(deadline, std::memory_order_relaxed);
  stats_generation.store(generation, std::memory_order_release);
}

bool isUsbLoggingClientActive() {
  const uint32_t generation = stats_generation.load(std::memory_order_acquire);
  if (!generation || generation != session_generation.load(std::memory_order_acquire))
    return false;
  uint32_t deadline = stats_deadline.load(std::memory_order_relaxed);
  if (!deadline) return false;
  if (int32_t(deadline - millis()) > 0) return true;
  // Latch expiry, so millis wrapping weeks later cannot revive an old poll.
  // Compare the timestamp, not just the session: an owner-task renewal that
  // raced this expiry must retain its new deadline.
  stats_deadline.compare_exchange_strong(deadline, 0);
  return false;
}

void clearUsbLoggingClientActivity() {
  // A callback racing a poll invalidates that poll's old generation without
  // blocking either the USB owner task or the application loop.
  session_generation.fetch_add(1, std::memory_order_acq_rel);
}

}  // namespace mesh
#else
namespace mesh {
void noteUsbLoggingStatsCommand(const char*) {}
bool isUsbLoggingClientActive() { return false; }
void clearUsbLoggingClientActivity() {}
}  // namespace mesh
#endif  // MESH_USB_CONSOLE_COOPERATIVE
#endif  // ARDUINO
