#pragma once
#include <helpers/ui/GxEPDDisplay.h>
#include <cstring>

inline constexpr uint8_t u8g2_font_helvR08_tf[] = {0};
inline constexpr uint8_t u8g2_font_helvB08_tf[] = {1};
inline constexpr uint8_t u8g2_font_helvR10_tf[] = {2};
inline constexpr uint8_t u8g2_font_helvB10_tf[] = {3};

class U8G2_FOR_ADAFRUIT_GFX {
  Adafruit_GFX* _gfx = nullptr;
  unsigned _font = 0;
  uint16_t _foreground = 0, _background = 1;
public:
  void begin(Adafruit_GFX& gfx) { _gfx = &gfx; }
  void setForegroundColor(uint16_t color) { _foreground = color; }
  void setBackgroundColor(uint16_t color) { _background = color; }
  void setFont(const uint8_t* font) { _font = *font; }
  void setFontMode(int) {}
  void setFontDirection(int) {}
  // Helvetica 08/10 ascent/descent from the selected u8g2 font metadata.
  int getFontAscent() const { return _font >= 2 ? 11 : 8; }
  int getFontDescent() const { return _font >= 2 ? -3 : -2; }
  int getUTF8Width(const char* text) const {
    int width = 0;
    for (const auto* next = reinterpret_cast<const unsigned char*>(text); *next; ++next) {
      if ((*next & 0xC0) == 0x80) continue;
      width += (*next == 'i' || *next == 'l') ? 2 : *next == 'W' ? 8 : _font >= 2 ? 6 : 5;
    }
    return width;
  }
  void drawUTF8(int x, int baseline, const char* text) {
    const int width = getUTF8Width(text);
    assert(x >= 0 && x + width <= _gfx->width());
    assert(baseline - getFontAscent() >= 0);
    assert(baseline - getFontDescent() <= _gfx->height());
    _gfx->labels.push_back({x, baseline, width, getFontAscent(), getFontDescent(), (_font & 1) != 0,
                            _foreground, _background, text});
  }
};
