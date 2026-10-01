#pragma once

// Opt-in, bounded USB/SWD-readable diagnostics. Callbacks only write RAM;
// no serial I/O, allocation, PINs, keys, peer addresses or payloads are saved.
#if defined(MESH_NRF52_BLE_TRACE) && MESH_NRF52_BLE_TRACE
#include <Arduino.h>
#include <atomic>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static constexpr uint32_t MESH_BLE_TRACE_CAPACITY = 256;
struct MeshBleTraceRecord {
  uint32_t sequence, ms, event, handle, detail, extra;
};
struct MeshBleTraceSlot {
  // Sequentially consistent fields make the before/after sequence check
  // valid across tasks, including a reader racing with ring wraparound.
  std::atomic<uint32_t> sequence{0}, ms{0}, event{0}, handle{0}, detail{0}, extra{0};
};
struct MeshBleTraceBuffer {
  uint32_t magic = 0x424c4554, capacity = MESH_BLE_TRACE_CAPACITY;
  std::atomic<uint32_t> next{0}, dropped{0};
  std::atomic_flag writer = ATOMIC_FLAG_INIT;
  MeshBleTraceSlot records[MESH_BLE_TRACE_CAPACITY];
  std::atomic<uint32_t> dispatch_event{0}, dispatch_started{0}, max_dispatch_us{0};
  std::atomic<uint32_t> connects{0}, disconnects{0}, secured{0}, rx{0}, tx{0};
  std::atomic<uint32_t> last_reason{0}, last_disconnect_ms{0}, max_loop_gap_ms{0};
};
extern "C" { extern MeshBleTraceBuffer mesh_ble_trace; }
void meshBleTraceState(char* reply, size_t capacity);
static inline void meshBleTraceMax(std::atomic<uint32_t>& value, uint32_t sample) {
  uint32_t old = value.load(std::memory_order_relaxed);
  while (sample > old && !value.compare_exchange_weak(old, sample,
                                                        std::memory_order_relaxed)) {}
}
static inline void meshBleTrace(uint32_t event, uint32_t handle = 0xffff,
                                uint32_t detail = 0, uint32_t extra = 0) {
  // Never wait for a lower-priority writer: count contention instead. The
  // BLE worker must not be blocked by a USB reader or another diagnostic.
  if (mesh_ble_trace.writer.test_and_set(std::memory_order_acquire)) {
    mesh_ble_trace.dropped.fetch_add(1, std::memory_order_relaxed);
    return;
  }
  const uint32_t sequence = mesh_ble_trace.next.load(std::memory_order_relaxed) + 1;
  auto& record = mesh_ble_trace.records[(sequence - 1) % MESH_BLE_TRACE_CAPACITY];
  record.sequence.store(0);
  record.ms.store(millis());
  record.event.store(event);
  record.handle.store(handle);
  record.detail.store(detail);
  record.extra.store(extra);
  record.sequence.store(sequence);
  mesh_ble_trace.next.store(sequence, std::memory_order_release);
  mesh_ble_trace.writer.clear(std::memory_order_release);
}
static inline bool meshBleTraceRead(uint32_t sequence, MeshBleTraceRecord& r) {
  if (!sequence) return false;
  const auto& s = mesh_ble_trace.records[(sequence - 1) % MESH_BLE_TRACE_CAPACITY];
  r.sequence = s.sequence.load();
  r.ms = s.ms.load(); r.event = s.event.load(); r.handle = s.handle.load();
  r.detail = s.detail.load(); r.extra = s.extra.load();
  return r.sequence == sequence && s.sequence.load() == sequence;
}
static inline void meshBleTraceDispatchEnter(uint32_t event, uint32_t handle) {
  mesh_ble_trace.dispatch_started.store(micros(), std::memory_order_relaxed);
  mesh_ble_trace.dispatch_event.store(event, std::memory_order_release);
  meshBleTrace(0xe000 | event, handle);
}
static inline void meshBleTraceDispatchExit(uint32_t event, uint32_t handle) {
  const uint32_t elapsed = micros() - mesh_ble_trace.dispatch_started.load(
                                                        std::memory_order_relaxed);
  meshBleTraceMax(mesh_ble_trace.max_dispatch_us, elapsed);
  meshBleTrace(0xe100 | event, handle, elapsed);
  mesh_ble_trace.dispatch_event.store(0, std::memory_order_release);
}
static inline bool meshBleTraceCommand(const char* command, char* reply,
                                       size_t capacity) {
  if (!strcmp(command, "get bluetooth.trace.state")) {
    meshBleTraceState(reply, capacity);
    return true;
  }
  if (!strcmp(command, "get bluetooth.trace.stats")) {
    snprintf(reply, capacity,
        "> connects=%lu,disconnects=%lu,secured=%lu,rx=%lu,tx=%lu,reason=%lu,disconnect_ms=%lu",
        (unsigned long)mesh_ble_trace.connects.load(),
        (unsigned long)mesh_ble_trace.disconnects.load(),
        (unsigned long)mesh_ble_trace.secured.load(),
        (unsigned long)mesh_ble_trace.rx.load(), (unsigned long)mesh_ble_trace.tx.load(),
        (unsigned long)mesh_ble_trace.last_reason.load(),
        (unsigned long)mesh_ble_trace.last_disconnect_ms.load());
    return true;
  }
  if (!strcmp(command, "get bluetooth.trace.timing")) {
    const uint32_t event = mesh_ble_trace.dispatch_event.load(std::memory_order_acquire);
    snprintf(reply, capacity,
        "> uptime_ms=%lu,max_loop_gap_ms=%lu,max_dispatch_us=%lu,dispatch_event=%lu,dispatch_age_us=%lu",
        (unsigned long)millis(), (unsigned long)mesh_ble_trace.max_loop_gap_ms.load(),
        (unsigned long)mesh_ble_trace.max_dispatch_us.load(), (unsigned long)event,
        (unsigned long)(event ? micros() - mesh_ble_trace.dispatch_started.load() : 0));
    return true;
  }
  const char* prefix = "get bluetooth.trace";
  const size_t length = strlen(prefix);
  if (strncmp(command, prefix, length)
      || (command[length] && command[length] != ' ')) return false;
  if (!command[length]) {
    snprintf(reply, capacity, "> next=%lu,capacity=%lu,dropped=%lu,format=2",
             (unsigned long)mesh_ble_trace.next.load(std::memory_order_acquire),
             (unsigned long)mesh_ble_trace.capacity,
             (unsigned long)mesh_ble_trace.dropped.load());
    return true;
  }
  const char* value = command + length + 1;
  char* end = nullptr;
  errno = 0;
  const unsigned long sequence = strtoul(value, &end, 10);
  if (*value < '0' || *value > '9' || *end || sequence == 0
      || sequence > UINT32_MAX || errno == ERANGE) {
    snprintf(reply, capacity, "Error: use get bluetooth.trace <sequence>");
    return true;
  }
  MeshBleTraceRecord r;
  if (!meshBleTraceRead((uint32_t)sequence, r)) {
    snprintf(reply, capacity, "Error: trace record unavailable");
  } else {
    snprintf(reply, capacity, "> %lu,%lu,0x%04lx,%lu,%lu,%lu",
        (unsigned long)r.sequence, (unsigned long)r.ms,
        (unsigned long)r.event, (unsigned long)r.handle,
        (unsigned long)r.detail, (unsigned long)r.extra);
  }
  return true;
}
#else
#define meshBleTrace(...) do {} while (0)
#define meshBleTraceMax(...) do {} while (0)
#define meshBleTraceDispatchEnter(...) do {} while (0)
#define meshBleTraceDispatchExit(...) do {} while (0)
#endif
