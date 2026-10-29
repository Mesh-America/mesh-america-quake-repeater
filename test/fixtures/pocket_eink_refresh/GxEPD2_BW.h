#pragma once
#include <SPI.h>

#define GxEPD_BLACK 0
#define GxEPD_WHITE 1

namespace panel {
enum class Call { Full, Partial, PowerOff, Clear, WriteWhite, Hibernate,
                  PrepareFull, PreparePartial, Finish };
inline std::vector<Call> calls;
inline std::vector<std::string> images;
inline bool valid_history = false;
inline unsigned updates(Call kind) {
  unsigned count = 0;
  for (auto call : calls) if (call == kind) ++count;
  return count;
}
}

class Adafruit_GFX {
public:
  virtual ~Adafruit_GFX() = default;
};

struct GxEPD2_213_B74 {
  static constexpr int WIDTH = 128, WIDTH_VISIBLE = 122, HEIGHT = 250;
  GxEPD2_213_B74(int, int, int, int) {}
  void selectSPI(SPIClass&, SPISettings) {}
};

template<class T, int PageHeight> class GxEPD2_BW : public Adafruit_GFX {
  int rotation = 0;
  std::string image;
public:
  T epd2;
  explicit GxEPD2_BW(T model) : epd2(model) { static_assert(PageHeight == 250); }
  void init(int, bool, int, bool) {}
  void setRotation(int value) { rotation = value & 3; }
  int getRotation() const { return rotation; }
  int width() const { return rotation & 1 ? T::HEIGHT : T::WIDTH_VISIBLE; }
  int height() const { return rotation & 1 ? T::WIDTH_VISIBLE : T::HEIGHT; }
  void setTextWrap(bool) {}
  void setFullWindow() {}
  void setPartialWindow(int x, int y, int w, int h) {
    assert(x == 0 && y == 0 && w == width() && h == height());
  }
  void setFont(const int*) {}
  void setTextColor(int) {}
  void setCursor(int, int) {}
  void getTextBounds(const char* text, int, int, int16_t* x, int16_t* y,
                     uint16_t* w, uint16_t* h) {
    *x = 0; *y = -10; *w = std::strlen(text) * 6; *h = 12;
  }
  void print(const char* text) { image += text; }
  void fillScreen(int) { image.clear(); }
  void fillRect(int, int, int, int, int) {}
  void drawRect(int, int, int, int, int) {}
  void drawBitmap(int, int, const uint8_t*, int, int, int) {}
  void display(bool partial) {
    assert(!panel::calls.empty());
    assert(panel::calls.back() == (partial ? panel::Call::PreparePartial : panel::Call::PrepareFull)
           && "reset / configure immediately before uploading the drawn canvas");
    if (partial)
      assert(panel::valid_history && "partial refresh must follow a clean image after wake");
    panel::calls.push_back(partial ? panel::Call::Partial : panel::Call::Full);
    panel::images.push_back(image);
    // GxEPD2 synchronizes previous/current RAM after both update modes.
    panel::valid_history = true;
  }
  void powerOff() { panel::calls.push_back(panel::Call::PowerOff); }
  void clearScreen(int) {
    panel::calls.push_back(panel::Call::Clear);
    panel::valid_history = true;
  }
  void writeScreenBuffer(int) { panel::calls.push_back(panel::Call::WriteWhite); }
  void hibernate() {
    panel::calls.push_back(panel::Call::Hibernate);
    panel::valid_history = false;
  }
};
