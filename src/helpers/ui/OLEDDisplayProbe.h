#pragma once

#include <stdint.h>

namespace mesh { namespace ui {

enum class OLEDController : uint8_t { Absent, SSD1306, SH1106 };

enum class OLEDControllerMode : uint8_t { Auto, SSD1306, SH1106 };

constexpr OLEDControllerMode defaultOLEDControllerMode() {
#if defined(OLED_CONTROLLER_OVERRIDE)
  static_assert(OLED_CONTROLLER_OVERRIDE >= 0 && OLED_CONTROLLER_OVERRIDE <= 2,
                "OLED_CONTROLLER_OVERRIDE must be 0 (auto), 1 (SSD1306) or 2 (SH1106)");
  return static_cast<OLEDControllerMode>(OLED_CONTROLLER_OVERRIDE);
#else
  return OLEDControllerMode::Auto;
#endif
}

// Status-byte detection is used by ss_oled and Meshtastic. Only 0x08 is
// evidence of SH1106: some RAK1921 SSD1306 panels return the ambiguous 0x00.
// See https://github.com/meshtastic/firmware/pull/11265.
template <typename WireBus>
OLEDController detectOLEDController(WireBus& wire, uint8_t address) {
  wire.beginTransmission(address);
  if (wire.endTransmission() != 0) return OLEDController::Absent;

  int previous = -1;
  for (unsigned attempt = 0; attempt < 4; ++attempt) {
    wire.beginTransmission(address);
    const bool written = wire.write(uint8_t(0x00)) == 1;
    if (wire.endTransmission() != 0 || !written) break;
    if (wire.requestFrom(address, uint8_t(1)) != 1 || wire.available() != 1) break;
    const int status = wire.read();
    if (status < 0) break;
    const int nibble = status & 0x0f;
    if (nibble == previous)
      return nibble == 0x08 ? OLEDController::SH1106 : OLEDController::SSD1306;
    previous = nibble;
  }
  return OLEDController::SSD1306;
}

}} // namespace mesh::ui
