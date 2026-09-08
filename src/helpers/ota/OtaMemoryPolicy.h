#pragma once

// Qualified Full Companions stream host-provided firmware and need no permanent
// mOTA workspace. Apply the same policy to build.sh and direct PlatformIO builds.
#if defined(OTA_SEEDER_ONLY) && defined(COMPANION_RADIO_FULL) && \
    (defined(NRF52_PLATFORM) || \
     (defined(ESP32_PLATFORM) && defined(HELTEC_WIRELESS_PAPER)))
#ifndef OTA_SHARED_COMPANION_QUEUE
#define OTA_SHARED_COMPANION_QUEUE 1
#endif
#endif
