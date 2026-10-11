#pragma once

// Resolve the chip in every translation unit, including Dispatcher.cpp which
// includes this before Arduino.h. Otherwise different class layouts could be
// selected for the same build depending on include order.
#if !defined(MESH_ENABLE_MESHTEXT_CHAT) && defined(ESP32_PLATFORM) && defined(ARDUINO)
  #include <sdkconfig.h>
#endif

// Channel chat is an optional Companion transport, never a bridge. Start with
// the roomy ESP32-S3 Full/SX1262 family; other builds retain every existing
// feature and do not acquire the codec or its bounded raw-frame queue. A new
// family must qualify its modem implementation, flash and runtime RAM first.
#ifndef MESH_ENABLE_MESHTEXT_CHAT
  #if defined(ESP32_PLATFORM) && defined(CONFIG_IDF_TARGET_ESP32S3) \
      && defined(COMPANION_RADIO_FULL) && defined(USE_SX1262) \
      && !(defined(MESH_PRIMARY_ESPNOW) && MESH_PRIMARY_ESPNOW)
    #define MESH_ENABLE_MESHTEXT_CHAT 1
  #else
    #define MESH_ENABLE_MESHTEXT_CHAT 0
  #endif
#endif
