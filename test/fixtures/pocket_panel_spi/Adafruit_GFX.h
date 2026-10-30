#pragma once
#include <Arduino.h>
// Only GFX geometry is stubbed; GxEPD2_BW supplies the real canvas/drawPixel.
class Adafruit_GFX {
 public:
  const int16_t WIDTH, HEIGHT;
  Adafruit_GFX(int16_t w, int16_t h) : WIDTH(w), HEIGHT(h), w_(w), h_(h) {}
  virtual ~Adafruit_GFX() = default;
  virtual void drawPixel(int16_t, int16_t, uint16_t) = 0;
  int16_t width() const { return w_; }
  int16_t height() const { return h_; }
  uint8_t getRotation() const { return rotation_; }
  void setRotation(uint8_t value) {
    rotation_ = value & 3;
    w_ = rotation_ & 1 ? HEIGHT : WIDTH;
    h_ = rotation_ & 1 ? WIDTH : HEIGHT;
  }
 private:
  int16_t w_, h_;
  uint8_t rotation_ = 0;
};
