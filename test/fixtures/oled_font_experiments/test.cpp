#include "helpers/ui/OLEDDisplay.h"
#include <cassert>
#include <iostream>
#include <string>

#ifndef EXPECT_MODE
#define EXPECT_MODE 0
#endif
#ifndef MESHCORE_ARIAL_FONT_MODE
#define MESHCORE_ARIAL_FONT_MODE 0
#endif

static_assert(MESHCORE_ARIAL_FONT_MODE == EXPECT_MODE, "font experiment escaped its scope");

class TestDisplay : public OLEDDisplay {
public:
  TestDisplay() { setGeometry(GEOMETRY_RAWMODE, 96, 64); assert(init()); }
  void display() override {}
  int getBufferOffset() override { return 0; }
  bool connect() override { return true; }
  uint8_t initialFontHeight() const { return pgm_read_byte(fontData + HEIGHT_POS); }
  size_t framebufferSize() const { return displayBufferSize; }
  uint16_t drawRaw(int x, int y, const char *text, uint16_t count) {
    return drawStringInternal(x, y, text, count, getStringWidth(text, count, false), false);
  }
  uint16_t drawControl(const char *text) {
    return drawStringInternal(0, 0, text, 1, 0, false);
  }
};

struct Digest {
  uint64_t hash = UINT64_C(14695981039346656037);
  size_t cases = 0;
  void byte(uint8_t value) { hash = (hash ^ value) * UINT64_C(1099511628211); }
  void number(uint16_t value) { byte(value & 255); byte(value >> 8); }
  void framebuffer(const TestDisplay &display) {
    for (size_t i = 0; i < display.framebufferSize(); ++i) byte(display.buffer[i]);
    ++cases;
  }
  void print(const char *name) const {
    std::cout << name << ' ' << cases << ' ' << std::hex << hash << std::dec << '\n';
  }
};

static char identityLookup(uint8_t code) { return static_cast<char>(code); }

static void fillPattern(TestDisplay &display, unsigned seed) {
  for (size_t i = 0; i < display.framebufferSize(); ++i)
    display.buffer[i] = static_cast<uint8_t>(seed + 31 * i);
}

// Independent pixel-at-a-time reference for the uncompressed family trials.
// This does not reuse drawInternal's byte/shift implementation.
static void assertRawFamilyGlyph(TestDisplay &display, const uint8_t *font,
                                 unsigned code, unsigned font_index) {
  const unsigned line_height = font[HEIGHT_POS];
  const unsigned count = font[CHAR_NUM_POS];
  assert(font[FIRST_CHAR_POS] == 32 && count == 224);
  assert(line_height == (font_index == 0 ? 19 : 28));
  const unsigned table_index = 4 + 4 * (code - font[FIRST_CHAR_POS]);
  const unsigned offset = (unsigned(font[table_index]) << 8) | font[table_index + 1];
  const unsigned length = font[table_index + 2], advance = font[table_index + 3];
  char text[] = {static_cast<char>(code), 0};
  assert(display.getStringWidth(text, 1, false) == advance);
  uint8_t expected[96 * 64 / 8] = {};
  int top = 255, bottom = -1;
  const unsigned stride = (line_height + 7) / 8;
  if (offset == 0xffff) {
    assert(length == 0);
  } else {
    assert(length && advance);
    const auto *bitmap = font + 4 + 4 * count + offset;
    assert(length <= advance * stride);
    for (unsigned byte = 0; byte < length; ++byte)
      for (unsigned bit = 0; bit < 8; ++bit)
        if (bitmap[byte] & (1 << bit)) {
          const unsigned x = byte / stride, y = 8 * (byte % stride) + bit;
          assert(x < advance && y < line_height);  // No clipped/padding-row ink.
          top = min(top, int(y)); bottom = max(bottom, int(y));
          if (x < 96) expected[x + 96 * (y / 8)] |= 1 << (y & 7);
        }
    assert(bottom >= top);  // Every drawable Latin-1 glyph still has pixels.
  }
  if (code == 'H') {
    assert(top == (font_index == 0 ? 3 : 5));
    assert(bottom == (font_index == 0 ? 14 : 21));
    assert(bottom - top + 1 == (font_index == 0 ? 12 : 17));
  }
  assert(std::memcmp(expected, display.buffer, sizeof(expected)) == 0);
}

int main() {
  TestDisplay display;
  const uint8_t initial_height = display.initialFontHeight();
  assert(initial_height == (EXPECT_MODE == 0 ? 13 : 19));
  std::cout << "initial " << static_cast<unsigned>(initial_height) << '\n';
  const uint8_t *fonts[] = {ArialMT_Plain_16, ArialMT_Plain_24};
  Digest glyphs, clipping, utf8, wrapping, controls, bitmaps, logs, custom;
  unsigned font_index = 0;
  for (const auto *font : fonts) {
    display.setFont(font);
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    display.setFontTableLookupFunction(identityLookup);
    for (unsigned code = 32; code <= 255; ++code) {
      char text[] = {static_cast<char>(code), 0};
      display.clear();
      display.setColor(WHITE);
      glyphs.number(display.getStringWidth(text, 1, false));
      glyphs.number(display.drawRaw(0, 0, text, 1));
      if (EXPECT_MODE >= 4 && EXPECT_MODE <= 8)
        assertRawFamilyGlyph(display, font, code, font_index);
      glyphs.framebuffer(display);
    }
    if (EXPECT_MODE >= 4) {
      unsigned drawable = 0;
      for (unsigned slot = 0; slot < 224; ++slot)
        if (font[4 + 4 * slot] != 255 || font[5 + 4 * slot] != 255) ++drawable;
      assert(drawable == 189);
    }

    const char samples[] = {'A', 'W', 'j', static_cast<char>(0xc0), static_cast<char>(0xff)};
    for (char sample : samples)
      for (int color = BLACK; color <= INVERSE; ++color)
        for (int offset = 0; offset < 8; ++offset)
          for (int edge = 0; edge < 4; ++edge) {
            char text[] = {sample, 0};
            const int x[] = {-9, 4, 93, 4};
            const int y[] = {offset, -19 + offset, offset, 60 + offset};
            fillPattern(display, 0x53);
            display.setColor(static_cast<OLEDDISPLAY_COLOR>(color));
            clipping.number(display.drawRaw(x[edge], y[edge], text, 1));
            clipping.framebuffer(display);
          }

    // Control codes must never index before the font's first character.
    for (unsigned code = 1; code < 32; ++code) {
      if (code == '\n') continue;
      char text[] = {static_cast<char>(code), 0};
      display.clear();
      // Original mode 0 has no guard for control-code width lookup. Compare
      // against its safe drawing behavior, not its out-of-bounds width read.
      const auto width = EXPECT_MODE ? display.getStringWidth(text, 1, false) : 0;
      assert(width == 0);
      controls.number(width);
      controls.number(display.drawControl(text));
      for (size_t i = 0; i < display.framebufferSize(); ++i) assert(display.buffer[i] == 0);
      controls.framebuffer(display);
    }

    display.setFontTableLookupFunction(DefaultFontTableLookup);
    const char *strings[] = {
      "MeshCore repeater 909.5 MHz",
      "\xc3\x80\xc3\x89\xc3\xa9 \xc2\xb0\xc2\xb5\xc3\xbf",
      "\xc2\xa0\xc2\xa3\xc2\xa9 \xe2\x82\xac",
      "Line one / Line two",
      "unsupported \xf0\x9f\x93\xbb emoji",
    };
    for (const char *text : strings)
      for (int alignment = TEXT_ALIGN_LEFT; alignment <= TEXT_ALIGN_CENTER_BOTH; ++alignment) {
        DefaultFontTableLookup(' ');
        fillPattern(display, 0x62);
        display.setColor(INVERSE);
        display.setTextAlignment(static_cast<OLEDDISPLAY_TEXT_ALIGNMENT>(alignment));
        utf8.number(display.getStringWidth(text, std::strlen(text), true));
        utf8.number(display.drawString(48, 28, String(text)));
        utf8.framebuffer(display);
      }

    display.setTextAlignment(TEXT_ALIGN_LEFT);
    for (const char *text : strings)
      for (unsigned width : {18, 47, 96}) {
        DefaultFontTableLookup(' ');
        display.clear();
        display.setColor(WHITE);
        wrapping.number(display.drawStringMaxWidth(-2, 3, width, String(text)));
        wrapping.framebuffer(display);
      }

    if (EXPECT_MODE) {
      // Newline width lookup is independently checked for the experiment;
      // baseline font code indexes before its header for '\n'.
      const char a[] = {'A', 0}, w[] = {'W', 0};
      const auto expected = max(display.getStringWidth(a, 1), display.getStringWidth(w, 1));
      assert(display.getStringWidth("A\nW", 3) == expected);
      display.clear();
      assert(display.drawStringMaxWidth(0, 0, 96, String("A\nW")) == 0);
    }

    assert(display.setLogBuffer(4, 64));
    display.write("One\nTwo\nThree");
    display.clear();
    display.drawLogBuffer(0, 0);
    logs.framebuffer(display);
    ++font_index;
  }
  // The font decoder must not accidentally intercept regular bitmap drawing.
  const uint8_t bitmap[] = {0x5a, 0xff, 0x01, 0x80, 0x55, 0xaa, 0x00, 0x20};
  display.clear();
  display.drawFastImage(4, 4, 8, 8, bitmap);
  bitmaps.framebuffer(display);
  // Public setFont() remains compatible with user-supplied raw ThingPulse
  // fonts even when the built-in Arial glyph storage is compressed.
  static const uint8_t custom_font[] = {
    4, 8, 'A', 2,
    0, 0, 4, 4, 0, 4, 3, 3,
    0x3c, 0x42, 0x42, 0x3c, 0x7e, 0x4a, 0x34,
  };
  display.setFont(custom_font);
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFontTableLookupFunction(identityLookup);
  display.setColor(WHITE);
  display.clear();
  assert(display.getStringWidth("AB", 2, false) == 7);
  assert(display.drawRaw(0, 0, "AB", 2) == 2);
  assert(std::memcmp(display.buffer, custom_font + 12, 7) == 0);
  for (size_t i = 7; i < display.framebufferSize(); ++i) assert(display.buffer[i] == 0);
  custom.framebuffer(display);
  if (EXPECT_MODE) {
    // Unsupported codes in a shorter external font cannot index its bitmaps
    // as if they were extra metadata rows.
    display.clear();
    assert(display.getStringWidth("C", 1, false) == 0);
    display.drawRaw(0, 0, "C", 1);
    for (size_t i = 0; i < display.framebufferSize(); ++i) assert(display.buffer[i] == 0);
  }
  glyphs.print("glyphs"); clipping.print("clipping"); utf8.print("utf8");
  wrapping.print("wrapping"); controls.print("controls"); bitmaps.print("bitmaps");
  logs.print("logs"); custom.print("custom");
}
