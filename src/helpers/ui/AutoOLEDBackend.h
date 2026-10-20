#pragma once

#include <Adafruit_SSD1306.h>
#include <stdlib.h>
#include "OLEDDisplayProbe.h"

// Keep Adafruit's drawing, rotation and single 1 KiB framebuffer. SH1106 uses
// page writes into 132-column RAM, with the visible 128 columns starting at 2.
class AutoOLEDBackend : public Adafruit_SSD1306 {
  mesh::ui::OLEDController _controller = mesh::ui::OLEDController::Absent;
  bool _ready = false;

  bool writeCommands(const uint8_t* commands, uint8_t count) {
    wire->beginTransmission(i2caddr);
    const bool control = wire->write(uint8_t(0x00)) == 1;
    const bool payload = wire->write(commands, count) == count;
    return wire->endTransmission() == 0 && control && payload;
  }

public:
  using Adafruit_SSD1306::Adafruit_SSD1306;

  bool begin(uint8_t vcc, uint8_t address, bool reset, bool periphBegin) {
    _ready = false;
    i2caddr = address;
    if (periphBegin) wire->begin();
    if (reset && rstPin >= 0) {
      pinMode(rstPin, OUTPUT);
      digitalWrite(rstPin, HIGH);
      delay(1);
      digitalWrite(rstPin, LOW);
      delay(10);
      digitalWrite(rstPin, HIGH);
    }

#if defined(OLED_CONTROLLER_OVERRIDE) && OLED_CONTROLLER_OVERRIDE != 0
    static_assert(OLED_CONTROLLER_OVERRIDE == 1 || OLED_CONTROLLER_OVERRIDE == 2,
                  "OLED_CONTROLLER_OVERRIDE must be 0 (auto), 1 (SSD1306) or 2 (SH1106)");
    wire->beginTransmission(address);
    _controller = wire->endTransmission() != 0 ? mesh::ui::OLEDController::Absent
        : OLED_CONTROLLER_OVERRIDE == 2 ? mesh::ui::OLEDController::SH1106
                                        : mesh::ui::OLEDController::SSD1306;
#else
    _controller = mesh::ui::detectOLEDController(*wire, address);
#endif
    if (_controller == mesh::ui::OLEDController::Absent) return false;
    if (_controller == mesh::ui::OLEDController::SSD1306) {
      _ready = Adafruit_SSD1306::begin(vcc, address, false, false);
      return _ready;
    }

    if (!buffer && !(buffer = static_cast<uint8_t*>(malloc(WIDTH * ((HEIGHT + 7) / 8)))))
      return false;
    vccstate = vcc;
    clearDisplay();
    // SH1106G initialization, matching Adafruit_SH1106G::begin().
    static const uint8_t init[] = {
      0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
      0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xFF,
      0xD9, 0x1F, 0xDB, 0x40, 0x33, 0xA6, 0x20, 0x10, 0xA4
    };
    wire->setClock(wireClk);
    const bool initialized = writeCommands(init, sizeof(init));
    wire->setClock(restoreClk);
    if (!initialized) return false;
    delay(100);
    const uint8_t on = 0xAF;
    wire->setClock(wireClk);
    _ready = writeCommands(&on, 1);
    wire->setClock(restoreClk);
    return _ready;
  }

  mesh::ui::OLEDController controller() const { return _controller; }

  void ssd1306_command(uint8_t command) {
    if (_ready) Adafruit_SSD1306::ssd1306_command(command);
  }

  void display() {
    if (!_ready) return;
    if (_controller == mesh::ui::OLEDController::SSD1306) {
      Adafruit_SSD1306::display();
      return;
    }
    wire->setClock(wireClk);
    bool ok = true;
    for (uint8_t page = 0; ok && page < (HEIGHT + 7) / 8; ++page) {
      const uint8_t commands[] = {uint8_t(0xB0 | page), 0x02, 0x10};
      ok = writeCommands(commands, sizeof(commands));
      for (uint16_t column = 0; ok && column < WIDTH;) {
        const uint8_t count = WIDTH - column > 31 ? 31 : WIDTH - column;
        wire->beginTransmission(i2caddr);
        const bool control = wire->write(uint8_t(0x40)) == 1;
        const bool payload = wire->write(buffer + page * WIDTH + column, count) == count;
        ok = wire->endTransmission() == 0 && control && payload;
        column += count;
      }
    }
    wire->setClock(restoreClk);
  }
};
