#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace mesh {

// Timestamp is the node's advisory RTC, never proof of synchronized UTC.
// A reboot request is durable intent, not proof that a physical reset occurred.
struct UsbLoggingWatchdogEvent {
  enum Reason : uint8_t {
    HOST_ABSENT = 1, READER_ABSENT = 2, TX_STALLED = 4, CLIENT_INACTIVE = 8
  };
  enum Action : uint8_t {
    NONE = 0, SOFT_RECOVERY = 1, REENUMERATE = 2,
    REBOOT_REQUESTED = 3, REBOOT_CANCELLED = 4
  };
  uint8_t reasons = 0;
  uint8_t action = NONE;
  uint32_t epoch = 0;
  uint32_t uptime_seconds = 0;
  uint32_t sequence = 0;
  bool persisted = false;
};

constexpr size_t USB_WATCHDOG_EVENT_SIZE = 13;

inline void encodeUsbWatchdogEvent(uint8_t* out, const UsbLoggingWatchdogEvent& event) {
  memset(out, 0, USB_WATCHDOG_EVENT_SIZE);
  if (!event.sequence) return;
  out[0] = (event.reasons & 15u) | ((event.action & 7u) << 4)
      | (event.persisted ? 128u : 0u);
  const uint32_t words[] = {event.epoch, event.uptime_seconds, event.sequence};
  for (size_t i = 0; i < 3; ++i) {
    for (size_t j = 0; j < 4; ++j) out[1 + 4 * i + j] = words[i] >> (8 * j);
  }
}

// Relays need only validate the wire shape, not construct or decode timestamps.
// A nonempty record has a nonzero sequence, reason mask and known action.
inline bool validUsbWatchdogEvent(const uint8_t* in) {
  // memcpy keeps unaligned wire inputs legal; zero detection is independent
  // of the host byte order and lets small MCUs use a single word load.
  uint32_t sequence;
  memcpy(&sequence, in + 9, sizeof(sequence));
  if (sequence) {
    const uint8_t action = (in[0] >> 4) & 7u;
    return (in[0] & 15u) && action >= UsbLoggingWatchdogEvent::SOFT_RECOVERY
        && action <= UsbLoggingWatchdogEvent::REBOOT_CANCELLED;
  }
  uint32_t epoch, uptime;
  memcpy(&epoch, in + 1, sizeof(epoch));
  memcpy(&uptime, in + 5, sizeof(uptime));
  return !(in[0] | epoch | uptime);
}

inline bool decodeUsbWatchdogEvent(const uint8_t* in, UsbLoggingWatchdogEvent& event) {
  if (!validUsbWatchdogEvent(in)) return false;
  UsbLoggingWatchdogEvent decoded;
  decoded.reasons = in[0] & 15u;
  decoded.action = (in[0] >> 4) & 7u;
  decoded.persisted = in[0] & 128u;
  uint32_t* words[] = {&decoded.epoch, &decoded.uptime_seconds, &decoded.sequence};
  for (size_t i = 0; i < 3; ++i) {
    for (size_t j = 0; j < 4; ++j) *words[i] |= uint32_t(in[1 + 4 * i + j]) << (8 * j);
  }
  event = decoded;
  return true;
}

inline const char* usbWatchdogActionName(uint8_t action) {
  switch (action) {
    case UsbLoggingWatchdogEvent::SOFT_RECOVERY: return "soft-recovery";
    case UsbLoggingWatchdogEvent::REENUMERATE: return "reenumerate";
    case UsbLoggingWatchdogEvent::REBOOT_REQUESTED: return "reboot-requested";
    case UsbLoggingWatchdogEvent::REBOOT_CANCELLED: return "reboot-cancelled";
    default: return "none";
  }
}

}  // namespace mesh
