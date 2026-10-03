#pragma once

#include "IdentityStore.h"
#include "UsbLoggingStatus.h"
#include <stddef.h>

namespace mesh {

// A separate versioned statefile keeps all deployed role preference offsets
// unchanged. New nodes default to Auto (14 continuous healthy USB days before
// arming). Volatile fallback filesystems must never authorize a reboot.
void loadUsbLoggingWatchdog(FILESYSTEM* fs, bool durable = true,
                            uint32_t (*epoch_seconds)() = nullptr);
bool handleUsbLoggingWatchdogCommand(const char* command, char* reply,
                                    size_t capacity);

// Call from the application loop only. The callback protects protocol, radio
// and dirty-contact ownership and is rechecked after the durable tier commit.
// True authorizes the caller's board.reboot(); this helper never reboots.
bool serviceUsbLoggingWatchdog(bool (*safe)(void*), void* context = nullptr);
bool isUsbLoggingWatchdogArmed();
bool isUsbLoggingWatchdogUpdateActive();

}  // namespace mesh
