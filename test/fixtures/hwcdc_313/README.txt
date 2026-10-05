The original Arduino-ESP32 3.1.3 HWCDC.cpp and version header are copied from
the framework source resolved by the Xiao_C6_repeater_ build:
framework-arduinoespressif32, ESP_ARDUINO_VERSION 3.1.3

Upstream repository: https://github.com/espressif/arduino-esp32
The original source retains its Espressif copyright and Apache-2.0 header.

HWCDC.cpp SHA256:
a09e99f1a37931269625019f51f1541a1185cce83f686d7aca4204ecdfea91dd

Tests use the real ISR and application reset helpers against host peripheral
stubs. The 3.1.3 transform only adds the startup predicate declaration and
wraps BUS_RESET event posting. Existing TX, FIFO, PHY, and pin-manager code is
kept byte-for-byte. Unlike 3.3.11, this driver has no partial-TX suffix stash or
TX interrupt spinlock; these tests retain those existing behavior limits.
These tests do not substitute for physical C6 testing.
