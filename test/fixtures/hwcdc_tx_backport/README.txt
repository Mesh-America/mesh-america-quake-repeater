Exact upstream Arduino-ESP32 2.0.17 HWCDC.cpp fixture for fail-closed TX transform.
Source: https://github.com/espressif/arduino-esp32/blob/2.0.17/cores/esp32/HWCDC.cpp
Revision: dcc1105b0cf1322a437b354c336f2abf72b7e512
SHA256: d0a8ca606c2729c8522a041113285dbf27033c22a5a6af8649a7305ffe84c449
Version-header source: same tag cores/esp32/esp_arduino_version.h.
Both files preserve their upstream copyright and Apache-2.0 notices.
The full source is necessary to verify the exact input fingerprint and all
producer/ISR/reset replacement sites without a PlatformIO package dependency.
Underlying correction: upstream commit2ecad233178bfbba9c584ffd9f67e941d84adbb7,
https://github.com/espressif/arduino-esp32/pull/12606.
