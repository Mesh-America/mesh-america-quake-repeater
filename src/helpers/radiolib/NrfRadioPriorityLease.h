#pragma once

#ifndef MC_NRF_RADIO_PROFILE_PRIORITY
#define MC_NRF_RADIO_PROFILE_PRIORITY 0
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY != 0 && MC_NRF_RADIO_PROFILE_PRIORITY != 1
#error "Radio profile priority experiment must be 0 or 1"
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY
#if !defined(NRF52_PLATFORM) || !defined(MESH_HIL_PROFILE_TIMING) || !MESH_HIL_PROFILE_TIMING
#error "Radio profile priority experiment requires nRF52 HIL profile timing"
#endif

#include <Arduino.h>
#include <stdint.h>
#include <string.h>

namespace mesh { namespace radiopriority {

static_assert(configMAX_PRIORITIES > TASK_PRIO_HIGH + 1,
              "Radio priority experiment needs a task priority above USB");
static constexpr uint32_t DeadlineTicks = 32; // about 0.977 ms at 32768 Hz
static constexpr uint32_t RtcMask = 0x00ffffff;
enum YieldDecision { Inactive, Suppress, Expired };

// Independent single-word counters for private read-only SWD observation.
// They are not an atomic multiword snapshot. All policy state is loop-owned.
struct Capture {
  uint32_t magic, version, size_bytes, deadline_ticks;
  uint32_t active, entries, releases, expired;
  uint32_t skipped_not_owned, skipped_isr, skipped_nested;
  uint32_t skipped_task, skipped_priority, suppressed_yields, frame_checks;
};
struct Work {
  TaskHandle_t owner;
  uint32_t started_ticks;
  bool active;
};
extern "C" {
extern volatile Capture mesh_hil_radio_priority;
}
extern Work work;

inline bool enter(bool owned_warm_rx) {
  auto& capture = mesh_hil_radio_priority;
  if (!owned_warm_rx) { ++capture.skipped_not_owned; return false; }
  if (isInISR()) { ++capture.skipped_isr; return false; }
  if (work.active) { ++capture.skipped_nested; return false; }
  const TaskHandle_t owner = xTaskGetCurrentTaskHandle();
  const char* name = pcTaskGetName(owner);
  if (!name || strcmp(name, "loop") != 0) {
    ++capture.skipped_task;
    return false;
  }
  // Effective elevated/inherited priorities are not a restorable base
  // priority. This experiment admits only the known ordinary loop state.
  if (uxTaskPriorityGet(owner) != TASK_PRIO_LOW) {
    ++capture.skipped_priority;
    return false;
  }
  work.owner = owner;
  work.started_ticks = NRF_RTC2->COUNTER & RtcMask;
  work.active = true;
  capture.active = 1;
  ++capture.entries;
  vTaskPrioritySet(owner, TASK_PRIO_HIGH + 1);
  return true;
}

inline void release(bool expired = false) {
  if (!work.active) return;
  const TaskHandle_t owner = work.owner;
  work.active = false;
  work.owner = nullptr;
  mesh_hil_radio_priority.active = 0;
  ++mesh_hil_radio_priority.releases;
  if (expired) ++mesh_hil_radio_priority.expired;
  // Publish inactive BEFORE lowering priority, which can immediately let
  // the USB task run. Only an admitted priority-1 loop can own this lease.
  vTaskPrioritySet(owner, TASK_PRIO_LOW);
}

inline bool isOwner() {
  return work.active && !isInISR() && work.owner == xTaskGetCurrentTaskHandle();
}

inline bool checkDeadline() {
  if (!isOwner()) return false;
  if (((NRF_RTC2->COUNTER - work.started_ticks) & RtcMask) < DeadlineTicks)
    return true;
  release(true);
  return false;
}

inline void beforeFrame() {
  if (!isOwner()) return;
  ++mesh_hil_radio_priority.frame_checks;
  (void)checkDeadline();
}

inline YieldDecision beforeYield() {
  if (!isOwner()) return Inactive;
  if (!checkDeadline()) return Expired;
  ++mesh_hil_radio_priority.suppressed_yields;
  return Suppress;
}

// No scheduler suspension or IRQ masking. Normal BUSY polls lose the lease
// at the next yield/frame check after the RTC deadline. Existing nrfx's
// blocking transfer has no timeout hook: a hung peripheral cannot have a
// strict lease-time guarantee here and retains the board watchdog fallback.
class Lease {
  bool _owns;
public:
  explicit Lease(bool owned_warm_rx) : _owns(enter(owned_warm_rx)) {}
  Lease(const Lease&) = delete;
  Lease& operator=(const Lease&) = delete;
  ~Lease() { release(); }
  void release() {
    if (!_owns) return;
    _owns = false;
    radiopriority::release();
  }
};

} } // namespace mesh::radiopriority
#endif
