#pragma once

// STM32 images omit diagnostic history to preserve their existing flash limit.
// Share this default with radio wrappers so unused publication tracking is
// omitted too. A build may explicitly enable or disable the complete feature.
#ifndef MESH_ENABLE_TELEMETRY_HISTORY
  #if defined(STM32_PLATFORM)
    #define MESH_ENABLE_TELEMETRY_HISTORY 0
  #else
    #define MESH_ENABLE_TELEMETRY_HISTORY 1
  #endif
#endif

// Disabled builds retain callable unsupported defaults without enlarging each
// radio vtable or retaining unused publication/request implementations.
#if MESH_ENABLE_TELEMETRY_HISTORY
  #define MESH_TELEMETRY_HISTORY_VIRTUAL virtual
#else
  #define MESH_TELEMETRY_HISTORY_VIRTUAL
#endif
