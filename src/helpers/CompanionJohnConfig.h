#pragma once

#ifndef COMPANION_FEATURE_JOHN
  #if defined(COMPANION_RADIO_FULL) && defined(ENABLE_USB_INTERFACE) \
      && (defined(ESP32_PLATFORM) || defined(NRF52_PLATFORM))
    #define COMPANION_FEATURE_JOHN 1
  #else
    #define COMPANION_FEATURE_JOHN 0
  #endif
#endif

#if COMPANION_FEATURE_JOHN \
    && !(defined(COMPANION_RADIO_FULL) && defined(ENABLE_USB_INTERFACE) \
         && (defined(ESP32_PLATFORM) || defined(NRF52_PLATFORM)))
  #error "John lookup requires an ESP32 or nRF52 Full Companion USB terminal"
#endif
