#pragma once

#include <helpers/ui/PocketGuiConfig.h>

#if UI_POCKET_GUI

#include <helpers/ui/GxEPDDisplay.h>
#include <helpers/ui/DisplayTextLayout.h>
#include <U8g2_for_Adafruit_GFX.h>

namespace mesh {
namespace ui {
namespace pocket {

// Reader pagination and drawing share the Pocket UI's small Helvetica font.
// Keep this adapter persistent: the Reader already decodes on the loop stack.
class PocketReaderDisplay : public DisplayDriver {
  GxEPDDisplay& _display;
  U8G2_FOR_ADAFRUIT_GFX _font;
  int _x = 0, _y = 0;
  ColorVal _color = UIColor::primary_txt;

public:
  explicit PocketReaderDisplay(GxEPDDisplay& display)
      : DisplayDriver(display.width(), display.height()), _display(display) {
    _font.begin(display.gfx());
    _font.setFont(u8g2_font_helvR08_tf);
    _font.setFontMode(1);
    _font.setFontDirection(0);
  }

  bool isOn() override { return _display.isOn(); }
  bool isEink() override { return true; }
  void forceFullRefresh() override { _display.forceFullRefresh(); }
  void turnOn() override { _display.turnOn(); }
  void turnOff() override { _display.turnOff(); }
  void clear() override { _display.clear(); }
  void startFrame(ColorVal background = UIColor::window_bkg) override {
    _display.startFrame(background);
  }
  void endFrame() override { _display.endFrame(); }
  void setTextSize(int) override {
    // Reader headings, body and controls use one small font. Sync dimensions
    // before measuring too, including when resuming after a rotation change.
    setDimensions(_display.width(), _display.height());
  }
  int textLineHeight() override {
    return _font.getFontAscent() - _font.getFontDescent() + 3;
  }
  void setColor(ColorVal color) override {
    _color = color;
    _display.setColor(color);
    _font.setForegroundColor(color);
    _font.setBackgroundColor(UIColor::window_bkg);
  }
  void setCursor(int x, int y) override { _x = x; _y = y; }
  uint16_t getTextWidth(const char* text) override {
    // Helvetica's j can extend one pixel before its cursor. Reserve that
    // bearing in both wrapping and drawing so a new row never clips it.
    return text && *text ? _font.getUTF8Width(text) + 1 : 0;
  }
  void print(const char* text) override {
    if (!text) return;
    // U8g2 draws directly into GFX; include its font, geometry and content in
    // the display CRC so text-only changes still trigger a panel update.
    const int geometry[] = {0x508, _x, _y, _color};
    _display.crcAdd(geometry, sizeof(geometry));
    _display.crcAdd(text, strlen(text));
    _font.drawUTF8(_x + 1, _y + _font.getFontAscent(), text);
    _x += getTextWidth(text);
  }
  void printWordWrap(const char* text, int max_width) override {
    if (max_width > width() - _x) max_width = width() - _x;
    const int glyph_height = _font.getFontAscent() - _font.getFontDescent();
    const int available = height() - _y;
    const int rows = available < glyph_height ? 0
        : 1 + (available - glyph_height) / textLineHeight();
    drawTextWrapped(*this, _x, _y, max_width, textLineHeight(), rows, text);
  }
  void fillRect(int x, int y, int width, int height) override {
    _display.fillRect(x, y, width, height);
  }
  void drawRect(int x, int y, int width, int height) override {
    _display.drawRect(x, y, width, height);
  }
  void drawXbm(int x, int y, const uint8_t* bits, int width, int height) override {
    _display.drawXbm(x, y, bits, width, height);
  }
};

}  // namespace pocket
}  // namespace ui
}  // namespace mesh

#endif
