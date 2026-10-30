#pragma once

#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

constexpr uint16_t GxEPD_BLACK = 0;
constexpr uint16_t GxEPD_WHITE = 1;

class Adafruit_GFX {
public:
  struct Text {
    int x, baseline, width, ascent, descent;
    bool bold;
    uint16_t foreground, background;
    std::string value;
  };
  std::vector<Text> labels;
  int w = 250, h = 122;
  int rotation = 3;
  int width() const { return w; }
  int height() const { return h; }
  void fillScreen(uint16_t) { labels.clear(); }
  void fillRect(int x, int y, int width, int height, uint16_t) {
    assert(x >= 0 && y >= 0 && width >= 0 && height >= 0);
    assert(x + width <= w && y + height <= h);
  }
  void drawPixel(int x, int y, uint16_t) {
    assert(x >= 0 && y >= 0 && x < w && y < h);
  }
  void drawLine(int x0, int y0, int x1, int y1, uint16_t) {
    assert(x0 >= 0 && y0 >= 0 && x1 >= 0 && y1 >= 0);
    assert(x0 < w && x1 < w && y0 < h && y1 < h);
  }
  void fillCircle(int x, int y, int, uint16_t color) { drawPixel(x, y, color); }
  void drawCircle(int x, int y, int, uint16_t color) { drawPixel(x, y, color); }
  bool contains(const char* value) const {
    for (const auto& text : labels) if (text.value == value) return true;
    return false;
  }
  unsigned occurrences(const char* value) const {
    unsigned result = 0;
    for (const auto& text : labels) if (text.value == value) ++result;
    return result;
  }
};

class GxEPDDisplay {
  Adafruit_GFX _gfx;
public:
  bool on = true;
  uint32_t hash = 2166136261U;
  bool isOn() const { return on; }
  Adafruit_GFX& gfx() { return _gfx; }
  void setNativeRotation(int rotation) {
    _gfx.rotation = rotation;
    _gfx.w = (rotation & 1) ? 250 : 122;
    _gfx.h = (rotation & 1) ? 122 : 250;
  }
  void crcAdd(const void* value, size_t size) {
    for (size_t i = 0; i < size; ++i) {
      hash ^= static_cast<const uint8_t*>(value)[i];
      hash *= 16777619U;
    }
  }
  void resetHash() { hash = 2166136261U; }
};
