Pinned source witnesses for the build-local Arduino-ESP32 scan fix.

WiFiScan.cpp is the complete, byte-exact Arduino-ESP32 2.0.17 source, preserving
its upstream copyright and LGPL notice:
https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/WiFi/src/WiFiScan.cpp
SHA256 e96ac4be873860dc2b441d6d01d6613eb4d06bb21e3f225c3f428619496e6c21
The local .gitattributes preserves upstream whitespace for this hashed witness.

wifi_scan_config.h retains the original license notice and the exact scan type
and configuration declarations from the pinned ESP-IDF 4.4.7 ESP32-S3 header:
https://github.com/espressif/esp-idf/blob/v4.4.7/components/esp_wifi/include/esp_wifi_types.h
This is a struct containing both active and passive dwell fields, not a union.

The test extracts and executes the actual scanNetworks method, capturing the
configuration at its esp_wifi_scan_start boundary. Where supported, compiler
automatic-variable poisoning makes the prior uninitialized fields deterministic.
Older host compilers use explicit poison only for the unsafe negative control.
The patched method is always executed unchanged. This proves initialization and
preservation of scan parameters, not radio timing or physical AP discovery.

Arduino 3.1.3 and 3.3.11 are explicitly unchanged to preserve existing recipes.
Their scan implementation and hardware behavior are outside this fix's scope.
