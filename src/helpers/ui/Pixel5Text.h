#pragma once

#include "DisplayDriver.h"
#include "DisplayTextLayout.h"
#include "Pixel5FontData.h"

namespace mesh {
namespace ui {

// Draw through the common pixel interface so OLED, TFT and U8g2 panels use
// identical glyphs. This stack wrapper leaves the driver's normal font alone.
class Pixel5Text : public DisplayDriver {
  DisplayDriver& _display;
  int _x = 0, _y = 0;

  static const Pixel5Glyph& glyph(uint8_t c) {
    return pixel5Glyphs[(c >= 32 && c <= 126 ? c : '?') - 32];
  }

public:
  explicit Pixel5Text(DisplayDriver& display)
      : DisplayDriver(display.width(), display.height()), _display(display) {}
  static constexpr int line_height = 7;
  static constexpr int glyph_height = 6; // 5px capitals plus descenders

  bool isOn() override { return _display.isOn(); }
  void turnOn() override { _display.turnOn(); }
  void turnOff() override { _display.turnOff(); }
  void clear() override { _display.clear(); }
  void startFrame(ColorVal bkg) override { _display.startFrame(bkg); }
  void endFrame() override { _display.endFrame(); }
  void setTextSize(int) override {} // This font deliberately has one size.
  void setColor(ColorVal color) override { _display.setColor(color); }
  void setCursor(int x, int y) override { _x = x; _y = y; }
  void fillRect(int x, int y, int w, int h) override {
    _display.fillRect(x, y, w, h);
  }
  void drawRect(int x, int y, int w, int h) override {
    _display.drawRect(x, y, w, h);
  }
  void drawXbm(int x, int y, const uint8_t* bits, int w, int h) override {
    _display.drawXbm(x, y, bits, w, h);
  }
  uint16_t getTextWidth(const char* str) override {
    uint16_t result = 0;
    while (*str) result += glyph((uint8_t)*str++).advance;
    return result;
  }
  void print(const char* str) override {
    while (*str) {
      const Pixel5Glyph& g = glyph((uint8_t)*str++);
      for (int row = 0; row < g.height; ++row) {
        const int y = _y + 4 + g.y_offset + row;
        if (y < 0 || y >= height()) continue;
        for (int col = 0; col < g.width; ++col) {
          const int bit = row * g.width + col;
          if (!(pixel5Bitmaps[g.bitmap_offset + bit / 8]
                & (0x80 >> (bit % 8)))) continue;
          const int x = _x + g.x_offset + col;
          if (x >= 0 && x < width()) _display.fillRect(x, y, 1, 1);
        }
      }
      _x += g.advance;
    }
  }
  void printWordWrap(const char* str, int max_width) override {
    if (max_width > width() - _x) max_width = width() - _x;
    const int lines = (height() - _y + line_height - glyph_height) / line_height;
    drawTextWrapped(*this, _x, _y, max_width, line_height, lines, str);
  }
};

inline int smallMessageLineCount(int height, int message_y) {
  const int remaining = height - message_y;
  return remaining < Pixel5Text::glyph_height ? 0
      : (remaining + Pixel5Text::line_height - Pixel5Text::glyph_height)
          / Pixel5Text::line_height;
}

inline void drawSmallMessageBody(DisplayDriver& display, const char* origin,
                                 const char* message, int origin_y = 14,
                                 int message_y = 21, int bottom = -1) {
  Pixel5Text text(display);
  char translated[161];
  text.translateUTF8ToBlocks(translated, origin, sizeof(translated));
  text.setColor(UIColor::secondary_txt);
  text.drawTextEllipsized(0, origin_y, display.width(), translated);
  text.translateUTF8ToBlocks(translated, message, sizeof(translated));
  text.setColor(UIColor::primary_txt);
  const int height = bottom < 0 || bottom > display.height()
      ? display.height() : bottom;
  drawTextWrapped(text, 0, message_y, display.width(), Pixel5Text::line_height,
                  smallMessageLineCount(height, message_y), translated);
}

}  // namespace ui
}  // namespace mesh
