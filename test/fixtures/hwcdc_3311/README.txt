The original Arduino-ESP32 3.3.11 HWCDC.cpp and version header are copied from
the installed, pinned framework source package:
framework-arduinoespressif32@src-533e72d076ed3cacc98127f709cb528f

Upstream repository: https://github.com/espressif/arduino-esp32
The original source retains its Espressif copyright and Apache-2.0 header.

HWCDC.cpp SHA256:
c5ed5fdd05aa0df9b74d390812643599223f96b459256718d0ad328aeaba6a8a

Tests use the real ISR and application reset helpers against host peripheral
stubs. The 3.3.11 transform only adds the startup predicate declaration and
wraps BUS_RESET event posting. Existing TX, FIFO, PHY, and pin-manager code is
kept byte-for-byte. These tests do not substitute for physical C6 testing.
