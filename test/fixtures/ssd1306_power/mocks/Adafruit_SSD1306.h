#pragma once

// Only the hardware/library boundary is doubled. The complete firmware driver,
// its public header, DisplayDriver and RefCountedDigitalPin compile unchanged.
#include <Arduino.h>
#include <Wire.h>
#include <string.h>

#define SSD1306_BLACK 0
#define SSD1306_WHITE 1
#define SSD1306_SWITCHCAPVCC 2
#define SSD1306_DISPLAYOFF 0xAE
#define SSD1306_DISPLAYON 0xAF

struct PanelState {
  bool allocation_ok = true;
  unsigned begins = 0, rotations = 0, frames = 0;
  unsigned on_commands = 0, off_commands = 0;
};
inline PanelState panel_state;

class Adafruit_SSD1306 {
  int16_t _width, _height;
  uint8_t _rotation = 0;
public:
  Adafruit_SSD1306(int16_t width, int16_t height, TwoWire*, int)
      : _width(width), _height(height) {}
  bool begin(int, uint8_t, bool, bool) {
    ++panel_state.begins;
    return panel_state.allocation_ok;
  }
  void setRotation(uint8_t rotation) { _rotation = rotation; ++panel_state.rotations; }
  int16_t width() const { return _rotation & 1 ? _height : _width; }
  int16_t height() const { return _rotation & 1 ? _width : _height; }
  void clearDisplay() {}
  void display() { ++panel_state.frames; }
  void ssd1306_command(uint8_t command) {
    if (command == SSD1306_DISPLAYON) ++panel_state.on_commands;
    if (command == SSD1306_DISPLAYOFF) ++panel_state.off_commands;
  }
  void setTextColor(uint16_t) {}
  void setTextSize(int) {}
  void setTextWrap(bool) {}
  void cp437(bool) {}
  void setCursor(int, int) {}
  void print(const char*) {}
  void fillRect(int, int, int, int, uint16_t) {}
  void drawRect(int, int, int, int, uint16_t) {}
  void drawBitmap(int, int, const uint8_t*, int, int, uint16_t) {}
  void getTextBounds(const char* text, int, int, int16_t* x, int16_t* y,
                     uint16_t* width, uint16_t* height) {
    *x = *y = 0;
    *width = strlen(text) * 6;
    *height = 8;
  }
};
