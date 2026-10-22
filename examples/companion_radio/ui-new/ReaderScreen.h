#pragma once
#include <helpers/CompanionReader.h>
#include <helpers/bible/Reader.h>
#include <helpers/ui/ReaderNavigationHint.h>
#if UI_SMALL_MESSAGE_FONT || UI_BUTTON_READER_HINT
#include <helpers/ui/SmallMessageText.h>
#endif

// Included by UITask.cpp after the task and MyMesh declarations. Only a small
// cursor/checkpoint object persists; the 4 KiB decode buffer is on demand.
class ReaderScreen : public UIScreen {
  UITask* _task;
  DisplayDriver* _display;
  mesh::bible::ReaderBookmark _bookmark;
  uint32_t _retry_at = 0;
  bool _loaded = false;
#if UI_READER_TOUCH_BAR
  mesh::ui::TouchNavigationBar _touch_bar;
#endif

  __attribute__((noinline)) void process(int direction, bool draw) {
    using namespace mesh::bible;
    char scratch[kBlockSize];
    const char* text = nullptr;
    Position pos = _bookmark.position();
    _display->setCompactText(false);
    _display->setTextSize(1);
    const int width = _display->width();
    const int header_height = _display->textLineHeight();
    // Narrow/rotated panels need separate start/end reference lines.
    const bool stacked_header = width < _display->getTextWidth("88:88")
        + _display->getTextWidth("88:88") + 4;
    const int header_content_height = header_height * (stacked_header ? 2 : 1);
#if UI_READER_TOUCH_BAR
    const int padded_header_height = mesh::ui::readerTouchHeaderHeight(header_content_height);
#else
    const int padded_header_height = header_content_height;
#endif
    const int header_text_y = (padded_header_height - header_content_height) / 2;
    const int top = padded_header_height + 2;
#if UI_SMALL_MESSAGE_FONT || UI_BUTTON_READER_HINT
    // Share message font selection and metrics, including rotated/tiny panels.
    mesh::ui::SmallMessageText compact(*_display);
#endif
    int bottom = _display->height();
#if UI_BUTTON_READER_HINT
    // Keep the hint compact on tiny displays even if the body font was
    // overridden. Reserve it before pagination so no verse text is hidden.
    const bool small_hint = _display->useSmallMessageFont();
    DisplayDriver& hint_text = small_hint
        ? static_cast<DisplayDriver&>(compact) : *_display;
#if UI_READER_TOUCH_BAR
    _touch_bar = mesh::ui::makeReaderTouchBar(hint_text, bottom, top - 1);
    bottom = _touch_bar.top;
#else
    const auto hint = mesh::ui::makeButtonReaderHintLayout(hint_text,
        small_hint ? compact.glyphHeight() : header_height, bottom,
        (millis() / 3000U) % 2 != 0);
    bottom = hint.top;
#endif
#endif
#if UI_SMALL_MESSAGE_FONT
    const bool small = _display->useSmallMessageFont();
    DisplayDriver& body = small ? static_cast<DisplayDriver&>(compact) : *_display;
    const int line_height = small ? compact.lineHeight() : header_height;
    int rows = small ? compact.lineCount(top, bottom) : (bottom - top) / line_height;
#else
    DisplayDriver& body = *_display;
    const int line_height = header_height;
    int rows = (bottom - top) / line_height;
#endif
    if (rows < 1) rows = 1;
    auto measure = [&body](const char* line) {
      char filtered[kReaderLineBytes];
      body.translateUTF8ToBlocks(filtered, line, sizeof(filtered));
      return body.getTextWidth(filtered);
    };

    // Stream adjacent verses through one decode buffer. Number labels are
    // display-only, so existing raw-text bookmarks remain compatible.
    uint16_t loaded_verse = kVerseCount;
    LookupResult result = LookupResult::Found;
    auto load = [&](uint16_t verse) {
      if (loaded_verse == verse) return true;
      result = mesh::readReaderVerse(referenceAt(verse), scratch, sizeof(scratch), text);
      if (result != LookupResult::Found) return false;
      memmove(scratch, text, strlen(text) + 1);
      loaded_verse = verse;
      return true;
    };
    char line[kReaderLineBytes];
    auto nextLine = [&](uint16_t verse, uint16_t offset) {
      char number[5] = {};
      if (!offset)
        snprintf(number, sizeof(number), "%u ", referenceAt(verse).verse);
      return readerLine(scratch, offset, width, measure, line, number);
    };

    if (load(pos.verse)) {
      // Resume on the line containing the saved word after font/rotation
      // changes, without tying the bookmark to a page or a number label.
      uint16_t offset = 0;
      while (scratch[offset]) {
        const uint16_t next = nextLine(pos.verse, offset);
        if (next > pos.offset || !scratch[next]) break;
        offset = next;
      }
      pos.offset = offset;

      if (direction < 0) {
        int remaining = rows;
        while (load(pos.verse)) {
          uint16_t count = 0;
          offset = 0;
          while (scratch[offset] && offset < pos.offset) {
            offset = nextLine(pos.verse, offset);
            ++count;
          }
          if (count >= remaining) {
            offset = 0;
            for (int skip = count - remaining; skip > 0; --skip)
              offset = nextLine(pos.verse, offset);
            pos.offset = offset;
            break;
          }
          remaining -= count;
          if (!pos.verse) { pos.offset = 0; break; }
          --pos.verse;
          pos.offset = kBlockSize - 1;
        }
      }

      Position cursor = pos, last = pos;
      if (direction >= 0 && result == LookupResult::Found) {
        body.setColor(UIColor::primary_txt);
        for (int row = 0; row < rows && cursor.verse < kVerseCount; ++row) {
          if (!load(cursor.verse)) break;
          last = cursor;
          cursor.offset = nextLine(cursor.verse, cursor.offset);
          if (draw) {
            char filtered[kReaderLineBytes];
            body.translateUTF8ToBlocks(filtered, line, sizeof(filtered));
            body.setCursor(0, top + row * line_height);
            body.print(filtered);
          }
          if (!scratch[cursor.offset]) { ++cursor.verse; cursor.offset = 0; }
        }
        // At the end keep the final page visible; never persist an EOF cursor.
        if (direction > 0 && cursor.verse < kVerseCount) pos = cursor;
      }
      if (result == LookupResult::Found) {
        _bookmark.move(pos, millis());
        if (!draw) return;
        char label[32], progress[16];
        const Reference ref = referenceAt(pos.verse);
        const Reference end = referenceAt(last.verse);
        snprintf(label, sizeof(label), "Reader %u:%u", ref.chapter, ref.verse);
        if (last.verse != pos.verse)
          snprintf(progress, sizeof(progress), "%u:%u",
                   end.chapter, end.verse);
        else progress[0] = 0;
        const int progress_width = _display->getTextWidth(progress);
        if (stacked_header || _display->getTextWidth(label) > width - progress_width - 4)
          snprintf(label, sizeof(label), "%u:%u", ref.chapter, ref.verse);
        _display->setColor(UIColor::title_txt);
        _display->drawTextEllipsized(0, header_text_y, stacked_header ? width : width - progress_width - 4, label);
        _display->drawTextRightAlign(width, header_text_y + (stacked_header ? header_height : 0), progress);
        _display->drawRect(0, top - 2, width, 1);
      } else if (draw) {
        body.setColor(UIColor::window_bkg);
        body.fillRect(0, top, width, bottom - top);
      }
    }
    if (result != LookupResult::Found) {
      if (draw) {
        body.setColor(UIColor::warning_txt);
        body.drawTextEllipsized(0, top, width, "Reader unavailable");
      } else _task->showAlert("Reader data error", 1500);
    }
    if (draw) {
#if UI_BUTTON_READER_HINT
#if UI_READER_TOUCH_BAR
      mesh::ui::drawReaderTouchBar(hint_text, _touch_bar);
#else
      mesh::ui::drawButtonReaderHint(hint_text, hint);
#endif
#endif
    }
  }

public:
#if UI_READER_TOUCH_BAR
  const mesh::ui::TouchNavigationBar* readerTouchBar() const { return &_touch_bar; }
#endif
  ReaderScreen(UITask* task, DisplayDriver* display) : _task(task), _display(display) {}
  void open() {
    if (!_loaded) {
      mesh::bible::Position pos;
      the_mesh.loadReaderBookmark(pos);
      _bookmark.restore(pos);
      _loaded = true;
    }
  }
  bool flush() {
    if (!_bookmark.dirty()) return true;
    if (!the_mesh.saveReaderBookmark(_bookmark.position())) {
      _retry_at = millis() + 30000;
      return false;
    }
    _bookmark.saved();
    _retry_at = 0;
    return true;
  }
  void poll() override {
    const uint32_t now = millis();
    if (_bookmark.due(now) && (!_retry_at || int32_t(now - _retry_at) >= 0)) flush();
  }
  int render(DisplayDriver&) override { process(0, true); return 1000; }
  bool handleInput(char c) override {
    const uint8_t key = static_cast<uint8_t>(c);
    if (key == KEY_NEXT || key == KEY_RIGHT) { process(1, false); return true; }
    if (key == KEY_PREV || key == KEY_LEFT) { process(-1, false); return true; }
    if (key == KEY_DOWN || key == KEY_UP) {
      using namespace mesh::bible;
      const Reference current = referenceAt(_bookmark.position().verse);
      const int chapter = current.chapter + (key == KEY_DOWN ? 1 : -1);
      Position pos;
      if (chapter >= 1 && chapter <= int(sizeof(kChapterVerses))
          && verseNumber({static_cast<uint8_t>(chapter), 1}, pos.verse)) {
        _bookmark.move(pos, millis());
      }
      return true;
    }
    if (key == KEY_ENTER || key == KEY_CANCEL) { _task->closeReader(); return true; }
    return false;
  }
};
