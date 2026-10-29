#pragma once

#ifndef MESH_HIL_IRQ_TIMING
#define MESH_HIL_IRQ_TIMING 0
#endif
#if MESH_HIL_IRQ_TIMING != 0 && MESH_HIL_IRQ_TIMING != 1
#error "IRQ timing observer flag must be 0 or 1"
#endif
#if MESH_HIL_IRQ_TIMING
#if !defined(NRF52_PLATFORM) || !defined(MESH_HIL_PROFILE_TIMING) || !MESH_HIL_PROFILE_TIMING
#error "IRQ timing observer requires nRF52 HIL profile timing"
#endif
#include <Arduino.h>
#include <atomic>
#include <stdint.h>

namespace mesh { namespace irqobserver {
// Append sources to retain the original per-source indices in captures.
enum Source : uint32_t { Rtc1, Gpiote, Uart0, Uart1, PowerClock, Usb, Scheduler, Twim0Spim0, SourceCount };
enum TaskKind : uint32_t { LoopTask, TimerTask, UsbTask, OtherTask, TaskKindCount };
struct Counter { uint32_t sequence, calls, cycles; };
struct Sample {
  uint32_t calls[SourceCount], cycles[SourceCount];
  uint32_t selected[TaskKindCount], selected_name[2];
};
struct Direction {
  uint32_t last_valid, worst_valid, last_ticks, worst_ticks;
  Sample last, worst;
};
struct Capture {
  uint32_t magic, version, size_bytes, sequence, source_count;
  uint32_t snapshots, retries, snapshot_failures;
  uint32_t last_result, last_direction;
  Direction direction[2];
};
struct Work {
  Sample begin{}, end{};
  uint32_t start_ticks = 0, end_ticks = 0;
  bool active = false, begin_valid = false, end_valid = false;
};
extern "C" {
extern volatile Counter mesh_hil_irq_counters[SourceCount];
extern volatile uint32_t mesh_hil_irq_selected[TaskKindCount + 2];
extern volatile Capture mesh_hil_radio_irqs;
}
extern std::atomic<uint32_t> revision;
extern Work work;

inline void barrier() {
#if defined(__arm__) || defined(__thumb__)
  __asm__ __volatile__("dmb" ::: "memory");
#else
  __asm__ __volatile__("" ::: "memory");
#endif
}
inline uint32_t clock() { return DWT->CYCCNT; }

// A source cannot interrupt itself. Other sources may nest; their own
// counters remain independent. Cycles are inclusive handler BODY time, so
// nested source totals must not be added as disjoint CPU time. Hardware
// exception entry/exit and the observer's bookkeeping are not in this sum.
inline void record(Source source, uint32_t cycles, const char* selected_name = nullptr) {
  auto& counter = mesh_hil_irq_counters[source];
  ++counter.sequence;
  barrier();
  ++counter.calls;
  counter.cycles += cycles;
  if (source == Scheduler) {
    uint32_t words[2] = {};
    if (selected_name) {
      for (unsigned i = 0; i < 8; ++i) {
        const uint8_t byte = static_cast<uint8_t>(selected_name[i]);
        if (!byte) break;
        words[i / 4] |= uint32_t(byte) << (8 * (i % 4));
      }
    }
    const TaskKind kind = words[0] == 0x706f6f6c ? LoopTask
        : (words[0] & 0x00ffffff) == 0x00726d54 ? TimerTask
        : words[0] == 0x64627375 ? UsbTask : OtherTask;
    ++mesh_hil_irq_selected[kind];
    mesh_hil_irq_selected[TaskKindCount] = words[0];
    mesh_hil_irq_selected[TaskKindCount + 1] = words[1];
  }
  barrier();
  ++counter.sequence;
  revision.fetch_add(1, std::memory_order_release);
}

inline bool readCounter(Source source, Sample& sample) {
  const auto& counter = mesh_hil_irq_counters[source];
  for (unsigned attempt = 0; attempt < 8; ++attempt) {
    const uint32_t before = counter.sequence;
    if (before & 1) continue;
    barrier();
    const uint32_t candidate_calls = counter.calls;
    const uint32_t candidate_cycles = counter.cycles;
    uint32_t selected[TaskKindCount + 2] = {};
    if (source == Scheduler) {
      for (unsigned i = 0; i < TaskKindCount + 2; ++i) selected[i] = mesh_hil_irq_selected[i];
    }
    barrier();
    if (before == counter.sequence) {
      sample.calls[source] = candidate_calls;
      sample.cycles[source] = candidate_cycles;
      if (source == Scheduler) {
        for (unsigned i = 0; i < TaskKindCount; ++i) sample.selected[i] = selected[i];
        sample.selected_name[0] = selected[TaskKindCount];
        sample.selected_name[1] = selected[TaskKindCount + 1];
      }
      return true;
    }
  }
  return false;
}

// Retry rather than mask any IRQ. The revision proves there was no completed
// observed handler between the first counter read and the clock endpoint.
// A bounded failure invalidates attribution while retaining ordinary timing.
inline bool snapshot(Sample& sample, uint32_t& ticks) {
  ++mesh_hil_radio_irqs.snapshots;
  for (unsigned attempt = 0; attempt < 8; ++attempt) {
    const uint32_t before = revision.load(std::memory_order_acquire);
    bool valid = true;
    for (uint32_t i = 0; i < SourceCount; ++i)
      valid = readCounter(static_cast<Source>(i), sample) && valid;
    const uint32_t candidate_ticks = clock();
    if (valid && before == revision.load(std::memory_order_acquire)) {
      ticks = candidate_ticks;
      return true;
    }
    ++mesh_hil_radio_irqs.retries;
  }
  ++mesh_hil_radio_irqs.snapshot_failures;
  ticks = clock();
  return false;
}

inline uint32_t begin() {
  work.active = true;
  work.end_valid = false;
  work.begin_valid = snapshot(work.begin, work.start_ticks);
  return work.start_ticks;
}
inline uint32_t endpoint() {
  if (!work.active) return clock();
  work.end_valid = snapshot(work.end, work.end_ticks);
  return work.end_ticks;
}
inline void finish(uint32_t direction_index, uint32_t result, bool worst) {
  if (!work.active || direction_index > 1) return;
  work.active = false;
  auto& capture = mesh_hil_radio_irqs;
  ++capture.sequence;
  barrier();
  capture.last_result = result;
  capture.last_direction = direction_index;
  auto& direction = capture.direction[direction_index];
  direction.last_valid = work.begin_valid && work.end_valid;
  direction.last_ticks = work.end_ticks - work.start_ticks;
  if (worst) {
    direction.worst_valid = direction.last_valid;
    direction.worst_ticks = direction.last_ticks;
  }
  for (uint32_t i = 0; i < SourceCount; ++i) {
    const uint32_t calls = direction.last_valid ? work.end.calls[i] - work.begin.calls[i] : 0;
    const uint32_t cycles = direction.last_valid ? work.end.cycles[i] - work.begin.cycles[i] : 0;
    direction.last.calls[i] = calls;
    direction.last.cycles[i] = cycles;
    if (worst) {
      direction.worst.calls[i] = calls;
      direction.worst.cycles[i] = cycles;
    }
  }
  for (uint32_t i = 0; i < TaskKindCount; ++i) {
    const uint32_t selected = direction.last_valid ? work.end.selected[i] - work.begin.selected[i] : 0;
    direction.last.selected[i] = selected;
    if (worst) direction.worst.selected[i] = selected;
  }
  for (unsigned i = 0; i < 2; ++i) {
    // Names only describe an actual selection within this hop, never a stale
    // last selection from a previous hop with no scheduling activity.
    const uint32_t name = direction.last_valid && direction.last.calls[Scheduler]
        ? work.end.selected_name[i] : 0;
    direction.last.selected_name[i] = name;
    if (worst) direction.worst.selected_name[i] = name;
  }
  barrier();
  ++capture.sequence;
}
static_assert(sizeof(Capture) == 424 && sizeof(Counter) == 12 && SourceCount == 8,
              "Unexpected IRQ observer ABI");
} } // namespace mesh::irqobserver
#endif
