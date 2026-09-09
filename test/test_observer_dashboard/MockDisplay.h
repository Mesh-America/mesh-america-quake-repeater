#pragma once

#include "helpers/ui/DisplayDriver.h"

#include <string>
#include <vector>

// Recording counterpart of the native portrait/landscape ST7789LCD profiles.
// Coordinates and normal font pixels are 1:1; explicit heading sizes remain.
class MockDisplay : public DisplayDriver {
public:
  enum Mode { PORTRAIT, LANDSCAPE };

  struct Op {
    enum Kind { FILL, RECT, TEXT } kind;
    int x, y, w, h;          // physical pixels
    ColorVal color;
    std::string text;
    int logical_size;
    bool scale_fallback;     // native drivers never shrink a string implicitly
  };

  explicit MockDisplay(Mode mode)
      : DisplayDriver(mode == PORTRAIT ? 240 : 320, mode == PORTRAIT ? 320 : 240), _mode(mode), _on(true), _color(0), _size(1), _cx(0), _cy(0) {}

  std::vector<Op> ops;

  int panelWidth() const { return _mode == PORTRAIT ? 240 : 320; }
  int panelHeight() const { return _mode == PORTRAIT ? 320 : 240; }

  void reset() { ops.clear(); }

  // --- DisplayDriver ---
  bool isOn() override { return _on; }
  void turnOn() override { _on = true; }
  void turnOff() override { _on = false; }
  void clear() override { ops.clear(); }
  void startFrame(ColorVal bkg = UIColor::window_bkg) override {
    ops.clear();
    ops.push_back(Op{Op::FILL, 0, 0, panelWidth(), panelHeight(), bkg, "", 1, false});
    _size = 1;
  }
  void setTextSize(int sz) override { _size = sz > 0 ? sz : 1; }
  void setColor(ColorVal c) override { _color = c; }
  void setCursor(int x, int y) override { _cx = x; _cy = y; }

  void print(const char* str) override {
    if (!str || !*str) return;
    int n = (int)strlen(str);
    int scale = physicalScale(_size);
    int px = mapX(_cx), py = mapY(_cy);
    bool fallback = false;
    ops.push_back(Op{Op::TEXT, px, py, n * 6 * scale, 8 * scale, _color, std::string(str), _size,
                     fallback});
    _cx += (int)((n * 6 * scale) / xScale());
  }

  void fillRect(int x, int y, int w, int h) override {
    ops.push_back(Op{Op::FILL, mapX(x), mapY(y), spanX(x, w), spanY(y, h), _color, "", _size,
                     false});
  }
  void drawRect(int x, int y, int w, int h) override {
    ops.push_back(Op{Op::RECT, mapX(x), mapY(y), spanX(x, w), spanY(y, h), _color, "", _size,
                     false});
  }
  void drawXbm(int, int, const uint8_t*, int, int) override {}
  void endFrame() override {}

  uint16_t getTextWidth(const char* str) override {
    if (!str) return 0;
    int n = (int)strlen(str);
    int scale = physicalScale(_size);
    return (uint16_t)(n * 6 * scale);
  }

private:
  Mode _mode;
  bool _on;
  ColorVal _color;
  int _size, _cx, _cy;

  float xScale() const { return 1; }
  int physicalScale(int logical) const { return logical; }
  int mapX(int x) const { return x; }
  int mapY(int y) const { return y; }
  int spanX(int, int w) const { return w; }
  int spanY(int, int h) const { return h; }
};
