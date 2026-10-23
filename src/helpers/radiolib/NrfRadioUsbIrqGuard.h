#pragma once

#include "NrfRadioProfileExperimentConfig.h"

#ifndef MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
#define MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD 0
#endif
#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD != 0 && MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD != 1
#error "Radio USB IRQ experiment must be 0 or 1"
#endif
#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
#if !defined(NRF52_PLATFORM) || !defined(MESH_HIL_PROFILE_TIMING) || !MESH_HIL_PROFILE_TIMING
#error "Radio USB IRQ experiment requires nRF52 HIL profile timing"
#endif
#include <Arduino.h>
#include <atomic>
#include <stdint.h>
#include <string.h>
#include <nrf_nvic.h>
#include <nrf_rtc.h>
#include "../nrf52/SoftDeviceState.h"
#if defined(NRFX_RTC2_ENABLED) && NRFX_RTC2_ENABLED
#error "Radio USB IRQ experiment cannot replace an nrfx RTC2 owner"
#endif

namespace mesh { namespace radiousb {

static constexpr uint32_t DeadlineTicks = 32; // about 0.977 ms at 32768 Hz
static constexpr uint32_t RtcMask = 0x00ffffff;
static constexpr uint32_t TimerPriority = 2; // SDK application IRQ; no RTOS API

// Private independent single-word observations, not an atomic snapshot.
struct Capture {
  uint32_t magic, version, size_bytes, deadline_ticks;
  uint32_t active, entries, releases, expired;
  uint32_t skipped_not_owned, skipped_isr, skipped_nested, skipped_task;
  uint32_t skipped_interrupts, skipped_usb, skipped_timer, skipped_priority, skipped_sdk;
  uint32_t last_sdk_result, last_sdk_enabled, last_nvic_result;
  uint32_t restore_errors, task_yields, frame_checks, usb_reenabled;
};
struct Work {
  TaskHandle_t owner = nullptr;
  uint32_t generation = 0, started_ticks = 0, cc0 = 0;
  uint32_t rtc_priority = 0, usb_priority = 0, inten = 0, evten = 0;
  std::atomic<uint32_t> active{0};
  std::atomic<uint32_t> usb_masked{0};
  bool softdevice_enabled = false;
};
extern "C" {
extern volatile Capture mesh_hil_radio_usb_irq;
}
extern Work work;

inline bool legalAppPriority(uint32_t priority) {
  return priority < 8 && priority != 0 && priority != 1 && priority != 4;
}

// The SDK app-NVIC helpers are inline, not SVCs, including in RTC2's ISR.
// SD-off may restore the unused timer's original priority zero exactly.
inline uint32_t setPriority(IRQn_Type irq, uint32_t priority) {
  if (work.softdevice_enabled) return sd_nvic_SetPriority(irq, priority);
  NVIC_SetPriority(irq, priority);
  return NRF_SUCCESS;
}
inline uint32_t enableIrq(IRQn_Type irq) {
  if (work.softdevice_enabled) return sd_nvic_EnableIRQ(irq);
  NVIC_EnableIRQ(irq);
  return NRF_SUCCESS;
}
inline uint32_t disableIrq(IRQn_Type irq) {
  if (work.softdevice_enabled) return sd_nvic_DisableIRQ(irq);
  NVIC_DisableIRQ(irq);
  return NRF_SUCCESS;
}
inline uint32_t clearTimerPending() {
  if (work.softdevice_enabled) return sd_nvic_ClearPendingIRQ(RTC2_IRQn);
  NVIC_ClearPendingIRQ(RTC2_IRQn);
  return NRF_SUCCESS;
}
inline void restored(uint32_t result) {
  mesh_hil_radio_usb_irq.last_nvic_result = result;
  if (result != NRF_SUCCESS) ++mesh_hil_radio_usb_irq.restore_errors;
}

inline void release(bool expired = false) {
  if (!work.active.load(std::memory_order_acquire)) return;
  // Mask only our timer IRQ. Its ISR can finish first if it interrupted this
  // call before the disable; recheck before touching the saved state.
  restored(disableIrq(RTC2_IRQn));
  if (!work.active.load(std::memory_order_acquire)) return;
  if (work.usb_masked.load(std::memory_order_acquire) && NVIC_GetEnableIRQ(USBD_IRQn))
    ++mesh_hil_radio_usb_irq.usb_reenabled;
  work.usb_masked.store(0, std::memory_order_release);
  work.active.store(0, std::memory_order_release);
  mesh_hil_radio_usb_irq.active = 0;
  ++mesh_hil_radio_usb_irq.releases;
  if (expired) ++mesh_hil_radio_usb_irq.expired;
  nrf_rtc_int_disable(NRF_RTC2, RTC_INTENSET_COMPARE0_Msk);
  nrf_rtc_event_clear(NRF_RTC2, NRF_RTC_EVENT_COMPARE_0);
  restored(clearTimerPending());
  nrf_rtc_cc_set(NRF_RTC2, 0, work.cc0);
  // Admission requires all RTC2 interrupt/PPI event enables to be zero;
  // only COMPARE0's interrupt was changed. Counter/prescaler never change.
  restored(setPriority(RTC2_IRQn, work.rtc_priority));
  restored(setPriority(USBD_IRQn, work.usb_priority));
  // Keep every pending USB event. Re-enabling lets the normal driver drain
  // it; no USBD peripheral registers, endpoint state or buffers are changed.
  restored(enableIrq(USBD_IRQn));
  work.owner = nullptr;
}

inline bool isOwner() {
  return work.active.load(std::memory_order_acquire) && !isInISR()
      && work.owner == xTaskGetCurrentTaskHandle();
}
inline bool checkDeadline() {
  if (!isOwner()) return false;
  // A USB reconfiguration/power event may re-enable its IRQ independently.
  // End the experiment rather than silently count that hop as isolated.
  if (work.usb_masked.load(std::memory_order_acquire) && NVIC_GetEnableIRQ(USBD_IRQn)) {
    release();
    return false;
  }
  if (((NRF_RTC2->COUNTER - work.started_ticks) & RtcMask) < DeadlineTicks)
    return true;
  release(true); // secondary check if an IRQ was briefly delayed
  return false;
}
inline void beforeFrame() {
  if (!isOwner()) return;
  ++mesh_hil_radio_usb_irq.frame_checks;
  (void)checkDeadline();
}
inline bool beforeYield() {
  if (!checkDeadline()) return false;
  ++mesh_hil_radio_usb_irq.task_yields;
  return true;
}

inline uint32_t enter(bool owned_warm_rx) {
  auto& capture = mesh_hil_radio_usb_irq;
  if (!owned_warm_rx) { ++capture.skipped_not_owned; return 0; }
  if (isInISR()) { ++capture.skipped_isr; return 0; }
  if (work.active.load(std::memory_order_acquire)) { ++capture.skipped_nested; return 0; }
  const TaskHandle_t owner = xTaskGetCurrentTaskHandle();
  const char* name = pcTaskGetName(owner);
  if (!name || strcmp(name, "loop") != 0 || uxTaskPriorityGet(owner) != TASK_PRIO_LOW) {
    ++capture.skipped_task;
    return 0;
  }
  if (__get_PRIMASK() || __get_BASEPRI() || __get_FAULTMASK() || nrf_nvic_state.__cr_flag) {
    ++capture.skipped_interrupts;
    return 0;
  }
  uint8_t enabled = 0;
  capture.last_sdk_result = mesh_nrf52::softdeviceIsEnabled(enabled);
  capture.last_sdk_enabled = enabled;
  if (capture.last_sdk_result != NRF_SUCCESS) { ++capture.skipped_sdk; return 0; }
  if (!NVIC_GetEnableIRQ(USBD_IRQn)) { ++capture.skipped_usb; return 0; }
  if (NVIC_GetEnableIRQ(RTC2_IRQn) || NVIC_GetPendingIRQ(RTC2_IRQn)
      || NRF_RTC2->INTENSET || NRF_RTC2->EVTEN || NRF_RTC2->PRESCALER) {
    ++capture.skipped_timer;
    return 0;
  }
  for (unsigned channel = 0; channel < 4; ++channel) {
    if (NRF_RTC2->EVENTS_COMPARE[channel]) { ++capture.skipped_timer; return 0; }
  }
  work.rtc_priority = NVIC_GetPriority(RTC2_IRQn);
  work.usb_priority = NVIC_GetPriority(USBD_IRQn);
  work.softdevice_enabled = enabled != 0;
  if (enabled && (!legalAppPriority(work.rtc_priority) || !legalAppPriority(work.usb_priority))) {
    ++capture.skipped_priority;
    return 0;
  }
  work.owner = owner;
  work.usb_masked.store(0, std::memory_order_release);
  work.cc0 = nrf_rtc_cc_get(NRF_RTC2, 0);
  work.inten = NRF_RTC2->INTENSET;
  work.evten = NRF_RTC2->EVTEN;
  work.started_ticks = NRF_RTC2->COUNTER & RtcMask;
  if (++work.generation == 0) ++work.generation;
  const uint32_t generation = work.generation;
  capture.last_nvic_result = setPriority(RTC2_IRQn, TimerPriority);
  if (capture.last_nvic_result != NRF_SUCCESS) {
    ++capture.skipped_sdk;
    work.owner = nullptr;
    return 0;
  }
  nrf_rtc_cc_set(NRF_RTC2, 0, (work.started_ticks + DeadlineTicks) & RtcMask);
  nrf_rtc_event_clear(NRF_RTC2, NRF_RTC_EVENT_COMPARE_0);
  work.active.store(1, std::memory_order_release);
  capture.active = 1;
  ++capture.entries;
  nrf_rtc_int_enable(NRF_RTC2, RTC_INTENSET_COMPARE0_Msk);
  capture.last_nvic_result = enableIrq(RTC2_IRQn);
  if (capture.last_nvic_result != NRF_SUCCESS) {
    ++capture.skipped_sdk;
    release();
    return 0;
  }
  if (!checkDeadline()) return 0;
  capture.last_nvic_result = disableIrq(USBD_IRQn);
  if (capture.last_nvic_result != NRF_SUCCESS) {
    ++capture.skipped_sdk;
    release();
    return 0;
  }
  work.usb_masked.store(1, std::memory_order_release);
  // An interrupt can expire between arming the timer and masking USB. Never
  // return with USB disabled after the expiry ISR has already restored it.
  if (!work.active.load(std::memory_order_acquire)) {
    work.usb_masked.store(0, std::memory_order_release);
    restored(enableIrq(USBD_IRQn));
    return 0;
  }
  if (!checkDeadline()) return 0;
  return generation;
}

inline void interrupt() {
  // Only our admitted COMPARE0 event is acknowledged. Existing timer owners
  // are rejected before admission; we never enable another RTC2 source.
  if (work.active.load(std::memory_order_acquire)
      && (NRF_RTC2->INTENSET & RTC_INTENSET_COMPARE0_Msk)
      && nrf_rtc_event_check(NRF_RTC2, NRF_RTC_EVENT_COMPARE_0)) release(true);
}

// Diagnostic causal isolation only. The timer restores USB even if an nrfx
// blocking transfer never returns. Higher-priority IRQs can delay that ISR;
// this is not an absolute hard real-time bound, nor a production policy.
class Guard {
  uint32_t _generation;
public:
  explicit Guard(bool owned_warm_rx) : _generation(enter(owned_warm_rx)) {}
  Guard(const Guard&) = delete;
  Guard& operator=(const Guard&) = delete;
  ~Guard() { release(); }
  void release() {
    if (!_generation) return;
    const uint32_t generation = _generation;
    _generation = 0;
    if (work.generation == generation) radiousb::release();
  }
};

static_assert(sizeof(Capture) == 96, "Unexpected USB IRQ diagnostic ABI");
} } // namespace mesh::radiousb
#endif
