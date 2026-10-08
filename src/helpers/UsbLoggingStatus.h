#pragma once

#include <stdint.h>
#include "UsbLoggingWatchdogEvent.h"

namespace mesh {

// Public, non-secret status shared by the CLI and management reports.
struct UsbLoggingStatus {
  bool supported = false;
  bool logging_enabled = false;
  bool watchdog_enabled = false;
  bool watchdog_auto = false;
  bool host_connected = false;
  bool reader_connected = false;
  bool logger_active = false;
  bool stalled = false;
  bool recovering = false;
  bool recovery_deferred = false;
  bool persistence_ready = false;
  uint8_t stage = 0;
  uint8_t backoff_step = 0;
  uint32_t retry_seconds = 3600;
  uint32_t inactive_seconds = 0;
  uint32_t auto_connected_seconds = 0;
  uint32_t recovery_count = 0;
  uint32_t reboot_count = 0;
  UsbLoggingWatchdogEvent last_event;
};

struct UsbLoggingObservation {
  bool supported = false;
  bool host_connected = false;
  bool reader_connected = false;
  bool pending = false;
  // Changes ONLY for a downstream USB TX-completion event, never enqueue,
  // queue discard, driver initialization, or our own recovery request.
  uint32_t tx_progress = 0;
};

enum class UsbLoggingRecoveryResult : uint8_t {
  Deferred, Attempted, Unsupported
};

UsbLoggingStatus usbLoggingStatus();
UsbLoggingObservation observeUsbLoggingTransport();
// stage 1: bounded local cleanup/probe; stage 2: descriptor-preserving USB
// re-enumeration. Neither function may reboot the board or wait for a host.
UsbLoggingRecoveryResult recoverUsbLoggingTransport(uint8_t stage);
// Optional watchdog heartbeat. Bounded and plaintext logging-only; accepting
// the record into a queue is not proof of host progress.
void probeUsbLoggingTransport();
bool isUsbLoggingTransportRecoveryPending();

}  // namespace mesh
