#pragma once

#include <stdint.h>
#include <limits.h>

// Pure attempt-accounting rules shared by the bridge and host tests. Publishing
// failures are deliberately separate: a broker that never connects cannot publish.
namespace MQTTConnectionHealth {

inline bool isOutageSlot(bool enabled, bool ready, bool connected) {
  return enabled && ready && !connected;
}

inline bool disconnectFailedAttempt(bool pending, bool was_connected) {
  return pending && !was_connected;
}

inline bool clearPendingAfterRejectedRequest(bool starting, bool was_pending) {
  // A failed start left nothing running; reconnect can reject a duplicate while
  // the previous attempt is still in flight.
  // Its callback may complete during/after the SDK call. A rejected duplicate
  // must leave the CURRENT flag untouched, never store true from a stale copy.
  return starting || !was_pending;
}

inline uint32_t incrementFailures(uint32_t count) {
  return count == UINT32_MAX ? count : count + 1;
}

inline int clampFailureTotal(uint64_t count) {
  return count > static_cast<uint64_t>(INT32_MAX) ? INT32_MAX : static_cast<int>(count);
}

struct Totals {
  int up = 0;
  int total = 0;
  int breakers = 0;
  uint64_t failures = 0;
  uint32_t worst_outage_ms = 0;
  bool outage_timed = false;
};

inline void addSlot(Totals& totals, bool enabled, bool ready, bool connected,
                    bool breaker, uint32_t outage_start, uint32_t now,
                    uint32_t connect_failures, uint32_t start_failures) {
  // A disabled/unready slot is not an outage, but its history remains counted.
  totals.failures += static_cast<uint64_t>(connect_failures) + start_failures;
  if (!enabled || !ready) return;
  totals.total++;
  if (breaker) totals.breakers++;
  if (connected) {
    totals.up++;
  } else if (outage_start != 0) {
    const uint32_t elapsed = now - outage_start; // wrap-safe under 49.7 days
    if (!totals.outage_timed || elapsed > totals.worst_outage_ms) {
      totals.worst_outage_ms = elapsed;
    }
    totals.outage_timed = true;
  }
}

}  // namespace MQTTConnectionHealth
