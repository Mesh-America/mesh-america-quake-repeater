#pragma once

#include <stdint.h>

namespace mesh {

// Keep a native USB radio awake through a short host reboot after a positive
// native USB host signal. No reported host means no grace. Some cores initially
// report a host before their first SOF check; that can arm only this bounded
// window, never an indefinite charger-only/battery sleep inhibitor.
class UsbHostSleepPolicy {
  uint32_t _last_host_seen_ms = 0;
  bool _host_present = false;
  bool _loss_grace_armed = false;

public:
  void observe(bool host_present, uint32_t now) {
    _host_present = host_present;
    if (host_present) {
      _last_host_seen_ms = now;
      _loss_grace_armed = true;
    }
  }

  bool shouldKeepAwake(uint32_t now, uint32_t grace_ms) {
    if (_host_present) return true;
    if (!_loss_grace_armed) return false;
    if (static_cast<uint32_t>(now - _last_host_seen_ms) < grace_ms) {
      return true;
    }
    // Disarm after expiry so another millis() cycle cannot revive an old signal.
    _loss_grace_armed = false;
    return false;
  }
};

}  // namespace mesh
