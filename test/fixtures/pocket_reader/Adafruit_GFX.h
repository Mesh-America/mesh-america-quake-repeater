#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>

class Print { public: virtual ~Print() = default; virtual size_t write(uint8_t) = 0; };

// Record the pixels emitted by the real U8g2 font decoder, including clipping.
class Adafruit_GFX {
public:
  int w = 250, h = 122, clipped = 0;
  std::vector<uint8_t> pixels = std::vector<uint8_t>(w * h, 1);
  int width() const { return w; }
  int height() const { return h; }
  void resize(int width, int height) {
    w = width; h = height; pixels.assign(w * h, 1); clipped = 0;
  }
  void fillScreen(uint16_t color) {
    std::fill(pixels.begin(), pixels.end(), color != 0); clipped = 0;
  }
  void drawPixel(int x, int y, uint16_t color) {
    if (x < 0 || y < 0 || x >= w || y >= h) {
      if (!clipped) std::fprintf(stderr, "clipped %d,%d on %dx%d\n", x, y, w, h);
      ++clipped; return;
    }
    pixels[y * w + x] = color != 0;
  }
  void drawFastHLine(int x, int y, int width, uint16_t color) {
    for (int i = 0; i < width; ++i) drawPixel(x + i, y, color);
  }
  void drawFastVLine(int x, int y, int height, uint16_t color) {
    for (int i = 0; i < height; ++i) drawPixel(x, y + i, color);
  }
  void fillRect(int x, int y, int width, int height, uint16_t color) {
    for (int row = 0; row < height; ++row) drawFastHLine(x, y + row, width, color);
  }
};
