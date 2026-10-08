#pragma once

#include <stdint.h>

// A compact request, not a runtime speech engine: all phrases are in flash.
enum class ButtonVoicePrompt : uint8_t {
  Ready,
  NotificationCleared,
  AdvertQueued,
  AdvertFailed,
  SoundOn,
  SoundOff,
  GpsOn,
  GpsOff,
  ActionFailed,
  UsbSetup,
  ShuttingDown,
  Restarting,
  AlertsSoundVibration,
  AlertsSoundOnly,
  AlertsVibrationOnly,
  AlertsSilent
};
