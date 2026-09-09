#ifdef ST7789

#include "ST7789Display.h"

// Native coordinates; controller RAM offsets are handled by ST7789Spi.

// Color scheme
ColorVal UIColor::window_bkg = OLEDDISPLAY_COLOR::BLACK;
ColorVal UIColor::title_bkg = OLEDDISPLAY_COLOR::BLACK;
ColorVal UIColor::title_txt = OLEDDISPLAY_COLOR::WHITE;
ColorVal UIColor::primary_txt = OLEDDISPLAY_COLOR::WHITE;
ColorVal UIColor::secondary_txt = OLEDDISPLAY_COLOR::WHITE;
ColorVal UIColor::warning_txt = OLEDDISPLAY_COLOR::WHITE;
ColorVal UIColor::popup_bkg = OLEDDISPLAY_COLOR::BLACK;
ColorVal UIColor::popup_txt = OLEDDISPLAY_COLOR::WHITE;
ColorVal UIColor::corp_blue = OLEDDISPLAY_COLOR::WHITE;

bool ST7789Display::begin() {
  if(!_isOn) {
    pinMode(PIN_TFT_VDD_CTL, OUTPUT);
    pinMode(PIN_TFT_LEDA_CTL, OUTPUT);
    digitalWrite(PIN_TFT_VDD_CTL, LOW);
  #ifdef PIN_TFT_LEDA_CTL_ACTIVE
    digitalWrite(PIN_TFT_LEDA_CTL, PIN_TFT_LEDA_CTL_ACTIVE);
  #else
    digitalWrite(PIN_TFT_LEDA_CTL, LOW);
  #endif
    digitalWrite(PIN_TFT_RST, HIGH);

    display.init();
    display.landscapeScreen();
    #ifdef DISPLAY_FLIP_VERTICALLY
    display.flipScreenVertically();
    #endif
    display.displayOn();
    setCursor(0,0);

    _isOn = true;
  }
  return true;
}

void ST7789Display::turnOn() {
  if (!_isOn) {
    // Restore power to the display but keep backlight off
    digitalWrite(PIN_TFT_VDD_CTL, LOW);
    digitalWrite(PIN_TFT_RST, HIGH);
    
    // Re-initialize the same native landscape geometry after wake.
    display.init();
    display.landscapeScreen();
    display.displayOn();
    #ifdef DISPLAY_FLIP_VERTICALLY
    display.flipScreenVertically();
    #endif
    delay(20);

    // Now turn on the backlight
  #ifdef PIN_TFT_LEDA_CTL_ACTIVE
    digitalWrite(PIN_TFT_LEDA_CTL, PIN_TFT_LEDA_CTL_ACTIVE);
  #else
    digitalWrite(PIN_TFT_LEDA_CTL, LOW);
  #endif    
    _isOn = true;
  }
}

void ST7789Display::turnOff() {
  digitalWrite(PIN_TFT_VDD_CTL, HIGH);
#ifdef PIN_TFT_LEDA_CTL_ACTIVE
  digitalWrite(PIN_TFT_LEDA_CTL, !PIN_TFT_LEDA_CTL_ACTIVE);
#else
  digitalWrite(PIN_TFT_LEDA_CTL, HIGH);
#endif
  digitalWrite(PIN_TFT_RST, LOW);
  _isOn = false;
}

void ST7789Display::clear() {
  display.clear();
}

void ST7789Display::startFrame(ColorVal bkg) {
  display.clear();  // TODO: use bkg
  setColor(UIColor::primary_txt);
  setTextSize(1);
}

void ST7789Display::setTextSize(int sz) {
  _line_height = sz == 2 ? 26 : 18;
  switch(sz) {
    case 1 :
      display.setFont(ArialMT_Plain_16);
      break;
    case 2 :
      display.setFont(ArialMT_Plain_24);
      break;
    default:
      display.setFont(ArialMT_Plain_16);
  }
}

void ST7789Display::setColor(ColorVal c) {
  _color = c;
  display.setColor((OLEDDISPLAY_COLOR)_color);
  display.setRGB(_color == OLEDDISPLAY_COLOR::WHITE ? ST77XX_WHITE : ST77XX_BLACK);
}

void ST7789Display::setCursor(int x, int y) {
  _x = x;
  _y = y;
}

void ST7789Display::print(const char* str) {
  display.drawString(_x, _y, str);
}

void ST7789Display::printWordWrap(const char* str, int max_width) {
  display.drawStringMaxWidth(_x, _y, max_width, str);
}

void ST7789Display::fillRect(int x, int y, int w, int h) {
  display.fillRect(x, y, w, h);
}

void ST7789Display::drawRect(int x, int y, int w, int h) {
  display.drawRect(x, y, w, h);
}

void ST7789Display::drawXbm(int x, int y, const uint8_t* bits, int w, int h) {
  if (!bits || w <= 0 || h <= 0) return;
  const int stride = (w + 7) / 8;
  for (int row = 0; row < h; ++row)
    for (int col = 0; col < w; ++col)
      if (pgm_read_byte(bits + row * stride + col / 8) & (0x80 >> (col & 7)))
        display.fillRect(x + col, y + row, 1, 1);
}

uint16_t ST7789Display::getTextWidth(const char* str) {
  return display.getStringWidth(str);
}

void ST7789Display::endFrame() {
  display.display();
}

#endif
