#pragma once

namespace mesh { namespace ota {

// Default own-image offering is for full-image platforms. Internal-only nRF52
// nodes retain the explicit diagnostic export used to capture delta bases, but
// do not automatically offer a full image their ordinary peers cannot install.
// Adaptive RAK and Tower builds must use the qualified application backend, not merely
// the presence of a NOR chip (or the temporary bootloader staging backend).
inline bool ota_self_serve_supported(bool external_application_storage = false) {
#if defined(OTA_SEEDER_ONLY)
  (void)external_application_storage;
  return false;                         // Companion sources offer host packages
#elif defined(ESP32_PLATFORM)
  (void)external_application_storage;
  return true;
#elif defined(NRF52_PLATFORM) && (defined(OTA_RAK_AUTO_STORE) || defined(OTA_TOWER_AUTO_STORE))
  return external_application_storage;
#elif defined(NRF52_PLATFORM) && (defined(OTA_QSPI_STORE) || defined(OTA_SD_STORE))
  (void)external_application_storage;
  return true;
#else
  (void)external_application_storage;
  return false;
#endif
}

} }
