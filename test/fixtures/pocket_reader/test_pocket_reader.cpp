#include <helpers/CompanionReader.h>
#include <helpers/bible/Reader.h>
#include <helpers/ui/UIScreen.h>
#include <examples/companion_radio/ui-new/PocketReaderDisplay.h>
#include <cassert>
#include <string>
#include <vector>
#include <cstdio>

using namespace mesh::bible;
static uint32_t test_now = 100;
uint32_t millis() { return test_now; }
ColorVal UIColor::window_bkg = 1, UIColor::title_bkg = 1, UIColor::title_txt = 0;
ColorVal UIColor::primary_txt = 0, UIColor::secondary_txt = 0, UIColor::warning_txt = 0;
ColorVal UIColor::popup_bkg = 1, UIColor::popup_txt = 0, UIColor::corp_blue = 0;
struct FakeMesh {
  Position saved = {};
  bool loadReaderBookmark(Position& p) { p = saved; return true; }
  bool saveReaderBookmark(Position p) { saved = p; return true; }
} the_mesh;
class UITask {
public:
  bool closed = false;
  void closeReader() { closed = true; }
  void showAlert(const char*, int) { assert(false); }
};
#include <examples/companion_radio/ui-new/ReaderScreen.h>

struct Line { Position pos; std::string text; };

// Independent word wrapping, measured by the same real library used on-device.
static std::vector<Line> expectedLines(int width, U8G2_FOR_ADAFRUIT_GFX& font) {
  std::vector<Line> lines;
  for (uint16_t verse = 0; verse < kVerseCount; ++verse) {
    char scratch[kBlockSize]; const char* text;
    assert(mesh::readReaderVerse(referenceAt(verse), scratch, sizeof(scratch), text)
        == LookupResult::Found);
    const std::string source(text);
    for (size_t offset = 0; offset < source.size();) {
      const std::string prefix = offset == 0 ? std::to_string(referenceAt(verse).verse) + " " : "";
      size_t count = 0;
      while (offset + count < source.size() && prefix.size() + count < kReaderLineBytes - 1) {
        const auto candidate = prefix + source.substr(offset, count + 1);
        if (count && font.getUTF8Width(candidate.c_str()) + 1 > width) break;
        ++count;
      }
      assert(count);
      if (offset + count < source.size()) {
        const size_t space = source.rfind(' ', offset + count - 1);
        if (space != std::string::npos && space > offset) count = space - offset;
      }
      lines.push_back({{verse, static_cast<uint16_t>(offset)}, prefix + source.substr(offset, count)});
      offset += count;
      while (offset < source.size() && source[offset] == ' ') ++offset;
    }
  }
  return lines;
}

int main() {
  GxEPDDisplay display;
  mesh::ui::pocket::PocketReaderDisplay reader_display(display);
  UITask task;
  Adafruit_GFX expected;
  U8G2_FOR_ADAFRUIT_GFX font;
  font.begin(expected); font.setFont(u8g2_font_helvR08_tf);
  font.setFontMode(1); font.setFontDirection(0);
  font.setForegroundColor(0); font.setBackgroundColor(1);
  assert(font.getFontAscent() == 8 && font.getFontDescent() == -2);
  assert(reader_display.textLineHeight() == 13);
  assert(reader_display.getTextWidth("Willing") == font.getUTF8Width("Willing") + 1);
  assert(reader_display.getTextWidth("iiii") < reader_display.getTextWidth("WWWW"));

  for (const auto& dimensions : {std::pair<int, int>{250, 122}, {122, 250}}) {
    display.resize(dimensions.first, dimensions.second);
    expected.resize(dimensions.first, dimensions.second);
    reader_display.setTextSize(1);
    assert(reader_display.width() == display.width() && reader_display.height() == display.height());
    const auto lines = expectedLines(display.width(), font);
    const int top = 15;
    auto hint = mesh::ui::makeButtonReaderHintLayout(reader_display, 13, display.height());
    const int rows = (hint.top - top) / 13;
    assert(rows >= 7);

    auto check = [&](ReaderScreen& reader, size_t first) {
      display.startFrame(); reader.render(display);
      assert(display.gfx().clipped == 0);
      expected.fillScreen(1);
      for (int row = 0; row < rows && first + row < lines.size(); ++row)
        font.drawUTF8(1, top + row * 13 + 8, lines[first + row].text.c_str());
      assert(expected.clipped == 0);
      for (int y = top; y < hint.top; ++y)
        for (int x = 0; x < display.width(); ++x)
          assert(display.gfx().pixels[y * display.width() + x] == expected.pixels[y * display.width() + x]);
      assert(reader.flush());
      assert(the_mesh.saved.verse == lines[first].pos.verse && the_mesh.saved.offset == lines[first].pos.offset);
    };

    // Every subsection can resume a previous raw-text bookmark, fill the
    // page across boundaries, advance, and return using the smaller font.
    uint16_t previous = kVerseCount;
    for (size_t first = 0; first < lines.size(); ++first) {
      if (lines[first].pos.verse == previous) continue;
      previous = lines[first].pos.verse;
      the_mesh.saved = lines[first].pos;
      ReaderScreen reader(&task, &reader_display); reader.open();
      check(reader, first);
      if (first + rows < lines.size()) {
        reader.handleInput(KEY_NEXT); check(reader, first + rows);
        reader.handleInput(KEY_PREV); check(reader, first);
      }
      // Saved offsets inside a word still normalize to its containing line.
      the_mesh.saved = lines[first].pos;
      the_mesh.saved.offset += 2;
      ReaderScreen resumed(&task, &reader_display); resumed.open();
      check(resumed, first);
    }
  }

  // Direct GFX text must contribute to the panel CRC on otherwise equal frames.
  auto hash = [&](const char* text, int x, int y, ColorVal color) {
    display.startFrame(); reader_display.setTextSize(1); reader_display.setColor(color);
    reader_display.setCursor(x, y); reader_display.print(text); return display.hash;
  };
  const auto original = hash("Reader", 0, 0, 0);
  assert(original == hash("Reader", 0, 0, 0));
  assert(original != hash("Reader!", 0, 0, 0));
  assert(original != hash("Reader", 1, 0, 0));
  assert(original != hash("Reader", 0, 1, 0));
  assert(original != hash("Reader", 0, 0, 1));
  display.startFrame(); reader_display.setColor(0); reader_display.setCursor(0, 0);
  reader_display.printWordWrap("A long line of words to wrap within the narrow reader viewport.", 50);
  assert(display.gfx().clipped == 0);
  std::puts("Pocket Reader: real Helvetica 08, all 879 subsections, pagination, resume, rotation and CRC passed");
}
