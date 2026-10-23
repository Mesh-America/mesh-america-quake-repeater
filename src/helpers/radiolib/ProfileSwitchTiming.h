#pragma once

// Private HIL instrumentation. Release builds contain neither its RAM state
// nor its timestamp/statistics calls. This does not alter radio commands.
#ifndef MESH_HIL_PROFILE_TIMING
#define MESH_HIL_PROFILE_TIMING 0
#endif

#if MESH_HIL_PROFILE_TIMING
#include <stdint.h>

namespace mesh {
namespace profiletiming {

enum Stage : uint32_t {
  BeginReconfigure = 0, Frequency, Modulation, Preamble, GuardMath,
  ProtocolAndCache, RxResume, Tail, Whole, StageCount
};
enum Result : uint32_t { Success = 0, Busy = 1, Failure = 2 };
static constexpr uint32_t Magic = 0x4d435054; // MCPT
static constexpr uint32_t Version = 1;
static constexpr uint32_t HistogramCount = 16;
static constexpr uint32_t HistogramWidthUs = 64;
#if defined(NRF52_PLATFORM)
static constexpr uint32_t ClockDivisor = 64;
#else
static constexpr uint32_t ClockDivisor = 1;
#endif
static constexpr uint32_t ClockHz = ClockDivisor * 1000000;

// All fields are uint32_t so the exact ELF has the same offsets on host and
// MCU; sums are split low/high words rather than ABI-dependent uint64_t.
struct StageStats {
  uint32_t count, sum_low_us, sum_high_us, min_us, max_us, last_us;
  uint32_t histogram[HistogramCount]; // final bucket includes >= 960 us
};
struct DirectionStats {
  uint32_t successes, busy, failures, last_result, last_mask;
  uint32_t last_us[StageCount];
  StageStats stage[StageCount];
};
struct Capture {
  uint32_t magic, version, size_bytes, sequence, clock_hz;
  uint32_t stage_count, histogram_count, histogram_width_us;
  uint32_t clock_state, clock_initializations; // bit0=already on, bit1=on now
  DirectionStats direction[2]; // index is originating profile: 0->1, 1->0
};
struct Work {
  uint32_t active, direction, start_ticks, previous_ticks, mask;
  uint32_t duration_us[StageCount];
};

// Read sequence, then the entire struct, then sequence again. Accept only
// equal even sequences and the expected magic/version/size. Never write it
// through SWD. Statistics publish after the measured switch has completed.
extern "C" {
extern volatile Capture mesh_hil_profile_timing;
extern Work mesh_hil_profile_timing_work;
}

inline void barrier() { __asm__ __volatile__("" ::: "memory"); }

// Call once during wrapper initialization, outside the measured switch.
// The nRF core enables trace and CYCCNT only; it does not enable debug/halt.
inline void initializeClock() {
#if defined(NRF52_PLATFORM)
  const bool was_enabled = dwt_enabled();
  if (!was_enabled) dwt_enable();
  mesh_hil_profile_timing.clock_state = (was_enabled ? 1U : 0U)
      | (dwt_enabled() ? 2U : 0U);
#else
  mesh_hil_profile_timing.clock_state = 2;
#endif
  ++mesh_hil_profile_timing.clock_initializations;
}

inline uint32_t readClock() {
#if defined(NRF52_PLATFORM)
  return DWT->CYCCNT;
#else
  return static_cast<uint32_t>(micros());
#endif
}

inline void begin(uint8_t from, uint8_t to, uint32_t now_ticks) {
  auto& work = mesh_hil_profile_timing_work;
  work.active = from < 2 && to < 2 && from != to;
  if (!work.active) return;
  work.direction = from;
  work.start_ticks = work.previous_ticks = now_ticks;
  work.mask = 0;
  for (uint32_t i = 0; i < StageCount; ++i) work.duration_us[i] = 0;
}

inline void mark(Stage stage, uint32_t now_ticks) {
  auto& work = mesh_hil_profile_timing_work;
  if (!work.active || stage >= Whole) return;
  // Subtract raw cycles BEFORE converting to microseconds. Arduino's nRF
  // micros() divides CYCCNT first and therefore wraps at about 67 seconds.
  work.duration_us[stage] = (now_ticks - work.previous_ticks) / ClockDivisor;
  work.previous_ticks = now_ticks;
  work.mask |= uint32_t(1) << stage;
}

inline void finish(Result result, uint32_t now_ticks) {
  auto& work = mesh_hil_profile_timing_work;
  if (!work.active) return;
  work.active = 0; // restoration or other applyParams calls cannot append
  work.duration_us[Whole] = (now_ticks - work.start_ticks) / ClockDivisor;
  work.mask |= uint32_t(1) << Whole;

  auto& capture = mesh_hil_profile_timing;
  ++capture.sequence;
  barrier();
  auto& direction = capture.direction[work.direction];
  direction.last_result = result;
  direction.last_mask = work.mask;
  if (result == Success) ++direction.successes;
  else if (result == Busy) ++direction.busy;
  else ++direction.failures;
  for (uint32_t i = 0; i < StageCount; ++i) {
    const uint32_t duration = work.duration_us[i];
    direction.last_us[i] = duration;
    if (result != Success || !(work.mask & (uint32_t(1) << i))) continue;
    auto& stats = direction.stage[i];
    const uint32_t previous_low = stats.sum_low_us;
    stats.sum_low_us = previous_low + duration;
    if (stats.sum_low_us < previous_low) ++stats.sum_high_us;
    if (stats.count == 0 || duration < stats.min_us) stats.min_us = duration;
    if (duration > stats.max_us) stats.max_us = duration;
    ++stats.count;
    stats.last_us = duration;
    const uint32_t bucket = duration / HistogramWidthUs;
    ++stats.histogram[bucket < HistogramCount ? bucket : HistogramCount - 1];
  }
  barrier();
  ++capture.sequence;
}

static_assert(sizeof(Capture) == 40 + 2 * (20 + StageCount * (4 + 88)),
              "Unexpected profile timing ABI");

} // namespace profiletiming
} // namespace mesh
#endif
