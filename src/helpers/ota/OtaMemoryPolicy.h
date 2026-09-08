#pragma once

// Full nRF52 Companions stream host-provided firmware and need no permanent
// mOTA workspace. Apply the same policy to build.sh and direct PlatformIO builds.
#if defined(NRF52_PLATFORM) && defined(OTA_SEEDER_ONLY) && defined(COMPANION_RADIO_FULL)
#ifndef OTA_SHARED_COMPANION_QUEUE
#define OTA_SHARED_COMPANION_QUEUE 1
#endif
#endif
