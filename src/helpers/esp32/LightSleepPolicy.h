#pragma once

#include <sdkconfig.h>
#include <helpers/PowerSavingDiagnostics.h>

// ENABLE_OTA alone also describes LoRa OTA on BLE-only images. Only link the
// WiFi SDK check when a compiled service can own that driver. Use build flags,
// rather than WITH_WEBCONFIG, which is defined by header inclusion order.
#if defined(WIFI_SSID) || defined(ENABLE_WIFI_INTERFACE) \
    || defined(WITH_MQTT_BRIDGE) || defined(WITH_ESPNOW_BRIDGE) || defined(WITH_UDP_BRIDGE) \
    || (defined(MESH_PRIMARY_ESPNOW) && MESH_PRIMARY_ESPNOW) \
    || defined(WIFI_OTA_SEEDER) || defined(ADMIN_PASSWORD) \
    || defined(COMPANION_RADIO_FULL)
#define MESH_ESP32_SLEEP_CHECK_WIFI 1
#include <esp_wifi.h>
#else
#define MESH_ESP32_SLEEP_CHECK_WIFI 0
#endif

#if defined(CONFIG_BT_ENABLED) && CONFIG_BT_ENABLED
#include <esp_bt.h>
#if defined(CONFIG_BLUEDROID_ENABLED) && CONFIG_BLUEDROID_ENABLED \
    && !defined(MESH_USE_NIMBLE_ARDUINO)
#include <esp_bt_main.h>
#endif
#endif

namespace mesh {
namespace esp32 {

// Explicit light sleep powers down the WiFi/Bluetooth peripheral, even when
// its connections are idle. Only automatic SDK sleep can preserve an active
// driver. Read the physical drivers: a logical service-off flag can precede
// asynchronous teardown, and ESP-NOW may own WiFi without Arduino's facade.
inline powerdiag::Reason manualLightSleepBlocker() {
#if defined(CONFIG_BT_ENABLED) && CONFIG_BT_ENABLED
  const esp_bt_controller_status_t controller = esp_bt_controller_get_status();
  if (controller != ESP_BT_CONTROLLER_STATUS_IDLE
      && controller != ESP_BT_CONTROLLER_STATUS_INITED)
    return powerdiag::Reason::Wireless;
#if defined(CONFIG_BLUEDROID_ENABLED) && CONFIG_BLUEDROID_ENABLED \
    && !defined(MESH_USE_NIMBLE_ARDUINO)
  const esp_bluedroid_status_t host = esp_bluedroid_get_status();
  if (host != ESP_BLUEDROID_STATUS_UNINITIALIZED
      && host != ESP_BLUEDROID_STATUS_INITIALIZED)
    return powerdiag::Reason::Wireless;
#endif
#endif
#if MESH_ESP32_SLEEP_CHECK_WIFI
  wifi_mode_t mode = WIFI_MODE_NULL;
  const esp_err_t result = esp_wifi_get_mode(&mode);
  if (result == ESP_OK)
    return mode == WIFI_MODE_NULL ? powerdiag::Reason::Count
                                  : powerdiag::Reason::Network;
  if (result == ESP_ERR_WIFI_NOT_INIT || result == ESP_ERR_WIFI_NOT_STARTED)
    return powerdiag::Reason::Count;
  return powerdiag::Reason::Network;  // An unknown driver state is not off.
#else
  return powerdiag::Reason::Count;
#endif
}

inline bool manualLightSleepReady() {
  return manualLightSleepBlocker() == powerdiag::Reason::Count;
}

}  // namespace esp32
}  // namespace mesh
