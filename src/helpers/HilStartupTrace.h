#pragma once

// Optional hardware-test timestamps only. Normal firmware has no extra output
// or timing work; phases are fixed literals and never contain node data.
#if defined(MESH_HIL_STARTUP_TRACE) && MESH_HIL_STARTUP_TRACE
#include <Arduino.h>
#include <helpers/UsbLogging.h>
namespace mesh {
inline void hilStartupTrace(const char* phase) {
  usbConsolePort().printf("HIL_BOOT phase=%s at=%lu\r\n", phase,
                         static_cast<unsigned long>(millis()));
}
}
#else
namespace mesh {
inline void hilStartupTrace(const char*) {}
}
#endif
