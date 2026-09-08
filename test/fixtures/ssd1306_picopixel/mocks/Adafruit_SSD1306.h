#pragma once
#include <Adafruit_GFX.h>
#include <Wire.h>
#include <vector>
#define SSD1306_BLACK 0
#define SSD1306_WHITE 1
#define SSD1306_SWITCHCAPVCC 2
#define SSD1306_DISPLAYON 0xAF
#define SSD1306_DISPLAYOFF 0xAE
class Adafruit_SSD1306 : public GFXcanvas1 {
public:
  struct Glyph { char c; int x, y, w, h; };
  std::vector<Glyph> glyphs;
  inline static Adafruit_SSD1306* last;
  int outside = 0;
  Adafruit_SSD1306(int w, int h, TwoWire*, int) : GFXcanvas1(w, h) { last=this; }
  bool begin(int, int, bool, bool) { return true; }
  void clearDisplay() { fillScreen(0); glyphs.clear(); outside=0; }
  void display() {}
  void ssd1306_command(int) {}
  void drawPixel(int16_t x, int16_t y, uint16_t c) override {
    if (x<0 || y<0 || x>=width() || y>=height()) ++outside;
    GFXcanvas1::drawPixel(x,y,c);
  }
  size_t write(uint8_t c) override {
    if (gfxFont && c>=gfxFont->first && c<=gfxFont->last) {
      const auto& g=gfxFont->glyph[c-gfxFont->first];
      glyphs.push_back({char(c), cursor_x+g.xOffset, cursor_y+g.yOffset, g.width, g.height});
    }
    return Adafruit_GFX::write(c);
  }
};
