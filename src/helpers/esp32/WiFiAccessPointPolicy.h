#pragma once

#include <WiFi.h>
#include <helpers/esp32/WiFiRadioPolicy.h>
#include <string.h>

namespace mesh {
namespace wifi {

inline bool accessPointStarted() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  return WiFi.AP.started();
#else
  return (WiFi.getStatusBits() & AP_STARTED_BIT) != 0;
#endif
}

// Arduino setters and a configured netif IP can outlive the AP_START event.
// Read the live driver before telling an operator that the hotspot is ready.
inline bool openAccessPointReady(const char* ssid, int channel) {
  wifi_mode_t mode = WIFI_MODE_NULL;
  wifi_config_t config = {};
  uint8_t protocol = 0;
  const size_t length = strlen(ssid);
  return accessPointStarted()
      && esp_wifi_get_mode(&mode) == ESP_OK && (mode & WIFI_MODE_AP)
      && esp_wifi_get_config(WIFI_IF_AP, &config) == ESP_OK
      && config.ap.ssid_len == length
      && memcmp(config.ap.ssid, ssid, length) == 0
      && config.ap.ssid_hidden == 0 && config.ap.authmode == WIFI_AUTH_OPEN
      && config.ap.channel == channel
      && esp_wifi_get_protocol(WIFI_IF_AP, &protocol) == ESP_OK
      && protocol == kAccessPointProtocolMask
      && static_cast<uint32_t>(WiFi.softAPIP()) != 0;
}

inline bool finishAccessPointScan() {
  // A failed Arduino scan can still have an active SDK scanner. scanDelete()
  // only releases results; cancel that scanner before enabling AP beacons.
  if (WiFi.scanComplete() < 0) {
    if (esp_wifi_scan_stop() != ESP_OK) return false;
    const uint32_t started = millis();
    while (WiFi.scanComplete() == WIFI_SCAN_RUNNING
           && millis() - started < 100) delay(20);
    WiFi.scanDelete();
  }
  return WiFi.scanComplete() != WIFI_SCAN_RUNNING;
}

inline bool scanBeforeAccessPoint() {
  // Use the same STA-only scan-first startup as WebConfig, including compact
  // OTA images without WebConfig. Shared ESP-NOW stays on its home channel.
  WiFi.scanDelete();
  WiFi.scanNetworks(true, false, false, 200, stationScanChannel());
  const uint32_t started = millis();
  while (WiFi.scanComplete() == WIFI_SCAN_RUNNING
         && millis() - started < 3600) delay(20);
  return finishAccessPointScan();
}

inline bool startOpenAccessPoint(const char* ssid, bool reuse_existing) {
  const int channel = accessPointChannel();
  // Repeated OTA commands retain joined clients when the AP is already live.
  if (reuse_existing && applyAccessPointProtocolMask() == ESP_OK
      && openAccessPointReady(ssid, channel)) return true;

  const bool connected = WiFi.status() == WL_CONNECTED
      && static_cast<uint32_t>(WiFi.localIP()) != 0;
  // Removing only AP keeps a station association and any ESP-NOW owner. It
  // also initializes a cold, previously disabled radio through Arduino.
  if (!WiFi.mode(WIFI_STA)) return false;
  const uint32_t stopped = millis();
  while (accessPointStarted() && millis() - stopped < 300) delay(20);
  if (accessPointStarted() || applyProtocolMask(WIFI_IF_STA) != ESP_OK)
    return false;
  // Do not scan away from a live LAN connection. An offline radio needs the
  // scan-first preparation before its first AP, rather than AP-only startup.
  if (!(connected ? finishAccessPointScan() : scanBeforeAccessPoint()))
    return false;

  const IPAddress ip(192, 168, 4, 1);
  const IPAddress mask(255, 255, 255, 0);
  bool ready = WiFi.softAPConfig(ip, ip, mask)
      && WiFi.softAP(ssid, nullptr, channel)
      && applyAccessPointProtocolMask() == ESP_OK;
  if (ready) {
    ready = false;
    const uint32_t started = millis();
    do {
      ready = openAccessPointReady(ssid, channel);
      if (!ready) delay(20);
    } while (!ready && millis() - started < 300);
  }
  if (!ready) WiFi.softAPdisconnect(true);
  return ready;
}

inline void stopTemporaryAccessPointRadio(bool started_radio) {
  // Only restore OFF when this AP initialized the radio. A station inherited
  // from WebConfig/MQTT belongs to the caller's service ownership policy.
  if (started_radio && !espNowChannelConstrained()
      && WiFi.status() != WL_CONNECTED) WiFi.mode(WIFI_OFF);
}

} // namespace wifi
} // namespace mesh
