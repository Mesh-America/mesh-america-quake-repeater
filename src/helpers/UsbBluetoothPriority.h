#pragma once

#include <stdint.h>

namespace mesh {

// USB enumeration, rather than VBUS or an open terminal, identifies a data
// host. Hold priority across brief bus resets so Bluetooth does not flap as
// the same host re-enumerates. A wall charger never acquires priority.
class UsbBluetoothPriority {
  bool inhibited_ = false;
  bool disconnect_pending_ = false;
  uint32_t disconnected_at_ = 0;

public:
  bool update(bool host_connected, uint32_t now) {
    if (host_connected) {
      inhibited_ = true;
      disconnect_pending_ = false;
    } else if (inhibited_) {
      if (!disconnect_pending_) {
        disconnected_at_ = now;
        disconnect_pending_ = true;
      } else if (uint32_t(now - disconnected_at_) >= 500) {
        inhibited_ = false;
        disconnect_pending_ = false;
      }
    }
    return inhibited_;
  }
};

}  // namespace mesh
