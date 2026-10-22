#pragma once
#include <helpers/ui/DisplayDriver.h>
#include <Adafruit_GFX.h>

constexpr uint16_t GxEPD_BLACK = 0, GxEPD_WHITE = 1;

class GxEPDDisplay : public DisplayDriver {
  Adafruit_GFX _gfx;
  ColorVal _color = 0;
public:
  bool on = true;
  uint32_t hash = 2166136261U;
  GxEPDDisplay() : DisplayDriver(250, 122) {}
  Adafruit_GFX& gfx() { return _gfx; }
  void resize(int width, int height) {
    setDimensions(width, height); _gfx.resize(width, height);
  }
  bool isOn() override { return on; }
  void turnOn() override { on = true; }
  void turnOff() override { on = false; }
  void clear() override { startFrame(); }
  void startFrame(ColorVal background = 1) override {
    hash = 2166136261U; _gfx.fillScreen(background);
  }
  void endFrame() override {}
  void setTextSize(int) override {}
  void setColor(ColorVal color) override { _color = color; }
  void setCursor(int, int) override {}
  void print(const char*) override { __builtin_trap(); }
  uint16_t getTextWidth(const char*) override { __builtin_trap(); }
  void fillRect(int x, int y, int width, int height) override {
    _gfx.fillRect(x, y, width, height, _color);
  }
  void drawRect(int x, int y, int width, int height) override {
    _gfx.drawFastHLine(x, y, width, _color);
    _gfx.drawFastHLine(x, y + height - 1, width, _color);
    _gfx.drawFastVLine(x, y, height, _color);
    _gfx.drawFastVLine(x + width - 1, y, height, _color);
  }
  void drawXbm(int, int, const uint8_t*, int, int) override {}
  void crcAdd(const void* value, size_t size) {
    for (size_t i = 0; i < size; ++i) {
      hash ^= static_cast<const uint8_t*>(value)[i]; hash *= 16777619U;
    }
  }
};
