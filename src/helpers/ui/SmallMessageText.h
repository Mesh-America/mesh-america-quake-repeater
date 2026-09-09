#pragma once

#include "DisplayDriver.h"
#include "DisplayTextLayout.h"
#include "Pixel5FontData.h"
#include "Squeezed6FontData.h"

namespace mesh {
namespace ui {

// Draw through the common pixel interface so OLED, TFT and U8g2 panels use
// identical glyphs. This stack wrapper leaves the driver's normal font alone.
class SmallMessageText : public DisplayDriver {
  DisplayDriver& _display;
  const bool _six_pixel;
  int _x = 0, _y = 0;

  const SmallFontGlyph& glyph(uint8_t c) const {
    const int index = (c >= 32 && c <= 126 ? c : '?') - 32;
    return _six_pixel ? squeezed6Glyphs[index] : pixel5Glyphs[index];
  }

public:
  explicit SmallMessageText(DisplayDriver& display)
      : DisplayDriver(display.width(), display.height()), _display(display),
        _six_pixel((width() >= 128 && height() >= 64)
                   || (width() >= 64 && height() >= 128)) {}

  // Preserve Picopixel on very tiny panels, including rotated 72x40 and
  // 128x32 screens. This wrapper is used only by the compact message UI.
  int capitalHeight() const { return _six_pixel ? 6 : 5; }
  int glyphHeight() const { return capitalHeight() + 1; } // descenders
  int lineHeight() const { return glyphHeight() + 1; } // blank row
  int lineCount(int y, int bottom = -1) const {
    if (bottom < 0 || bottom > height()) bottom = height();
    const int remaining = bottom - y;
    return remaining < glyphHeight() ? 0
        : 1 + (remaining - glyphHeight()) / lineHeight();
  }

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
      const SmallFontGlyph& g = glyph((uint8_t)*str++);
      const uint8_t* bitmap = _six_pixel ? squeezed6Bitmaps : pixel5Bitmaps;
      for (int row = 0; row < g.height; ++row) {
        const int y = _y + capitalHeight() - 1 + g.y_offset + row;
        if (y < 0 || y >= height()) continue;
        for (int col = 0; col < g.width; ++col) {
          const int bit = row * g.width + col;
          if (!(bitmap[g.bitmap_offset + bit / 8]
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
    drawTextWrapped(*this, _x, _y, max_width, lineHeight(), lineCount(_y), str);
  }
};

inline void drawSmallMessageBody(DisplayDriver& display, const char* origin,
                                 const char* message, int origin_y = 14,
                                 int bottom = -1) {
  SmallMessageText compact(display);
  const bool small = display.useSmallMessageFont();
  DisplayDriver& text = small ? static_cast<DisplayDriver&>(compact) : display;
  const int line_height = small ? compact.lineHeight() : display.textLineHeight();
  const int message_y = origin_y + line_height;
  if (bottom < 0 || bottom > display.height()) bottom = display.height();
  char translated[161];
  text.translateUTF8ToBlocks(translated, origin, sizeof(translated));
  text.setColor(UIColor::secondary_txt);
  text.drawTextEllipsized(0, origin_y, display.width(), translated);
  text.translateUTF8ToBlocks(translated, message, sizeof(translated));
  text.setColor(UIColor::primary_txt);
  drawTextWrapped(text, 0, message_y, display.width(), line_height,
                  small ? compact.lineCount(message_y, bottom)
                        : (bottom - message_y) / line_height, translated);
}

}  // namespace ui
}  // namespace mesh
