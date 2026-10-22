#pragma once

#include <helpers/ui/PocketGuiConfig.h>

#if UI_POCKET_GUI

// Message-board layout adapted from jackywashere's MeshCore Mesh Pocket
// MessageBoard (MIT), https://github.com/jackywashere/MeshCore-Mesh-Pocket-MessageBoard.
// The existing companion history, notifications and navigation remain shared.

#include <helpers/ui/GxEPDDisplay.h>
#include <helpers/ui/PocketGuiSettings.h>
#include <U8g2_for_Adafruit_GFX.h>
#include <stdio.h>

namespace mesh {
namespace ui {
namespace pocket {

struct Frame {
  uint32_t now = 0;
  uint64_t heard_millis = 0;
  float tz_offset = 0;
  int battery_percent = 0;
  const char* connection = nullptr;
  int page_index = 0;
  int page_count = 1;
  const char* hint = nullptr;
  int rotation = 3;
};

class PocketGui {
  static constexpr int HEADER_HEIGHT = 14;
  static constexpr int FOOTER_HEIGHT = 14;
  static constexpr uint32_t VALID_TIME = 1735689600UL;
  struct Line { uint8_t start, length; };

  GxEPDDisplay* _display = nullptr;
  Adafruit_GFX* _gfx = nullptr;
  U8G2_FOR_ADAFRUIT_GFX _font;
  bool _ready = false;
  Settings _settings;
  Frame _frame;
  BoardState _board;
  int _width = 250, _height = 122;
  uint16_t _ink = GxEPD_BLACK, _paper = GxEPD_WHITE;
  char _scratch[192];

  void hash(const void* value, size_t size) { _display->crcAdd(value, size); }
  void hashGeometry(int a, int b = 0, int c = 0, int d = 0) {
    const int value[] = {a, b, c, d};
    hash(value, sizeof(value));
  }
  void normal() { _font.setForegroundColor(_ink); _font.setBackgroundColor(_paper); }
  void inverse() { _font.setForegroundColor(_paper); _font.setBackgroundColor(_ink); }
  void font(bool bold = false, bool large = false) {
    const uint8_t key = (bold ? 1 : 0) | (large ? 2 : 0);
    hash(&key, 1);
    _font.setFont(large ? (bold ? u8g2_font_helvB10_tf : u8g2_font_helvR10_tf)
                        : (bold ? u8g2_font_helvB08_tf : u8g2_font_helvR08_tf));
  }
  int textWidth(const char* value) { return _font.getUTF8Width(value); }
  void fitText(char* value, int maximum_width) {
    while (textWidth(value) > maximum_width && value[0] != 0) {
      const size_t length = strlen(value);
      size_t previous = 0, cursor = 0;
      while (cursor < length) { previous = cursor; cursor = nextUtf8Character(value, cursor, length); }
      value[previous] = 0;
    }
  }
  void textRight(int x, int y, const char* value) { text(x - textWidth(value), y, value); }
  void textCentre(int x, int y, const char* value) { text(x - textWidth(value) / 2, y, value); }
  void fill(int x, int y, int width, int height, bool erase = false) {
    hashGeometry(x, y, width, height);
    hash(&erase, sizeof(erase));
    _gfx->fillRect(x, y, width, height, erase ? _paper : _ink);
  }
  void dots(int left, int right, int y) {
    hashGeometry(left, right, y);
    for (int x = left; x < right; x += 3) _gfx->drawPixel(x, y, _ink);
  }
  void textPart(int x, int y, const char* value, size_t length) {
    if (length >= sizeof(_scratch)) length = sizeof(_scratch) - 1;
    memcpy(_scratch, value, length);
    _scratch[length] = 0;
    text(x, y, _scratch);
  }
  int widthPart(const char* value, size_t length) {
    if (length >= sizeof(_scratch)) length = sizeof(_scratch) - 1;
    memcpy(_scratch, value, length);
    _scratch[length] = 0;
    return textWidth(_scratch);
  }
  int wrap(const char* value, int first_width, int width, Line* lines, int capacity) {
    const size_t length = strlen(value);
    size_t position = 0;
    int count = 0;
    while (position < length && count < capacity) {
      if (count != 0) while (position < length && value[position] == ' ') ++position;
      if (position == length) break;
      const int available = count == 0 ? first_width : width;
      size_t cursor = position, last_fit = position, last_space = position;
      while (cursor < length) {
        const size_t next = nextUtf8Character(value, cursor, length);
        if (widthPart(value + position, next - position) > available) break;
        if (value[cursor] == ' ') last_space = cursor;
        cursor = next;
        last_fit = next;
      }
      if (last_fit == position) {
        if (count == 0 && first_width < width) {
          lines[count++] = {(uint8_t)position, 0};
          continue;
        }
        last_fit = nextUtf8Character(value, position, length);
      } else if (last_fit < length && last_space > position) {
        last_fit = last_space;
      }
      lines[count++] = {(uint8_t)position, (uint8_t)(last_fit - position)};
      position = last_fit;
    }
    return count;
  }
  void clock(char* output, size_t size, uint32_t timestamp) const {
    const int64_t local = (int64_t)timestamp + (int32_t)(_frame.tz_offset * 3600.0f);
    int32_t seconds = (int32_t)(local % 86400);
    if (seconds < 0) seconds += 86400;
    snprintf(output, size, "%02u:%02u", (unsigned)(seconds / 3600),
             (unsigned)(seconds / 60 % 60));
  }
  void messageTime(char* output, size_t size, uint64_t heard_millis) const {
    const uint32_t age = messageAgeSeconds(_frame.heard_millis, heard_millis);
    if (age >= 20UL * 3600UL)
      snprintf(output, size, "%lud", (unsigned long)((age + 43200) / 86400));
    else if (_frame.now >= VALID_TIME && age <= _frame.now - VALID_TIME)
      clock(output, size, _frame.now - (uint32_t)age);
    else if (age >= 3600) snprintf(output, size, "%luh", (unsigned long)(age / 3600));
    else if (age >= 60) snprintf(output, size, "%lum", (unsigned long)(age / 60));
    else snprintf(output, size, "now");
  }

public:
  void begin(GxEPDDisplay& display, const Settings& settings, const Frame& frame) {
    _display = &display;
    _settings = settings;
    _frame = frame;
    display.setNativeRotation((frame.rotation + (settings.flip ? 2 : 0)) & 3);
    _gfx = &display.gfx();
    if (!_ready) { _font.begin(*_gfx); _ready = true; }
    _width = _gfx->width(); _height = _gfx->height();
    _ink = settings.dark ? GxEPD_WHITE : GxEPD_BLACK;
    _paper = settings.dark ? GxEPD_BLACK : GxEPD_WHITE;
    _gfx->fillScreen(_paper);
    _font.setFontMode(1); _font.setFontDirection(0);
    normal();
    const uint8_t appearance[] = {(uint8_t)frame.rotation, settings.flip, settings.dark};
    hash(appearance, sizeof(appearance));
  }
  int width() const { return _width; }
  int height() const { return _height; }
  int bodyTop() const { return HEADER_HEIGHT + 2; }
  int bodyBottom() const { return _height - FOOTER_HEIGHT - 2; }
  Adafruit_GFX& gfx() { return *_gfx; }
  uint16_t ink() const { return _ink; }
  uint16_t paper() const { return _paper; }
  void text(int x, int y, const char* value) {
    hashGeometry(x, y);
    hash(value, strlen(value));
    _font.drawUTF8(x, y, value);
  }
  void line(int x0, int y0, int x1, int y1) {
    hashGeometry(x0, y0, x1, y1);
    _gfx->drawLine(x0, y0, x1, y1, _ink);
  }
  void label(int x, int y, const char* value, bool bold = false) {
    font(bold);
    if (value != nullptr && x >= 0 && x < _width) {
      sanitizeText(_scratch, sizeof(_scratch), value, strlen(value));
      fitText(_scratch, _width - x);
      text(x, y, _scratch);
    }
    font();
  }
  void marker(int x, int y, bool self = false) {
    hashGeometry(x, y, self);
    _gfx->fillCircle(x, y, self ? 3 : 2, _ink);
    if (self) _gfx->drawCircle(x, y, 5, _ink);
  }
  void header(const char* title, const char* centre = nullptr) {
    fill(0, 0, _width, HEADER_HEIGHT);
    inverse(); font(true);
    char title_text[48];
    sanitizeText(title_text, sizeof(title_text), title, strlen(title));
    fitText(title_text, _width / 2 - 4);
    text(3, 10, title_text);
    const int title_end = 3 + textWidth(title_text);
    char status[16];
    const int battery = _frame.battery_percent < 0 ? 0 : _frame.battery_percent > 100 ? 100 : _frame.battery_percent;
    snprintf(status, sizeof(status), "%d%%", battery);
    textRight(_width - 3, 10, status);
    int right = _width - 8 - textWidth(status);
    if (_frame.connection != nullptr && _frame.connection[0] != 0) {
      const int connection_width = textWidth(_frame.connection);
      if (right - connection_width > title_end + 5) {
        textRight(right, 10, _frame.connection);
        right -= connection_width + 5;
      }
    }
    if (centre == nullptr && _frame.now >= VALID_TIME) {
      clock(status, sizeof(status), _frame.now); centre = status;
    }
    if (centre != nullptr) {
      const int centre_width = textWidth(centre);
      int x = (_width - centre_width) / 2;
      if (x + centre_width > right) x = right - centre_width;
      if (x > title_end + 5) text(x, 10, centre);
    }
    normal();
  }
  void footer(const char* hint = nullptr) {
    fill(0, _height - FOOTER_HEIGHT, _width, FOOTER_HEIGHT, true);
    dots(2, _width - 2, _height - FOOTER_HEIGHT);
    font(); normal();
    if (hint == nullptr) hint = _frame.hint != nullptr ? _frame.hint : "click next / 2x back";
    char hint_text[96];
    sanitizeText(hint_text, sizeof(hint_text), hint, strlen(hint));
    fitText(hint_text, _width - 6);
    text(3, _height - 3, hint_text);
    if (_frame.page_count > 1 && _frame.page_count <= 16) {
      const int step = 5;
      const int left = _width - 4 - (_frame.page_count - 1) * step;
      if (textWidth(hint_text) + 7 < left) {
        for (int i = 0; i < _frame.page_count; ++i) {
          const int x = left + i * step;
          if (i == _frame.page_index) _gfx->fillRect(x - 1, _height - 8, 3, 3, _ink);
          else _gfx->drawPixel(x, _height - 7, _ink);
        }
        hashGeometry(_frame.page_index, _frame.page_count);
      }
    }
  }

  template <typename History>
  unsigned boardCount(const History& history) const {
    unsigned count = 0;
    for (size_t age = 0; age < history.count(); ++age) {
      const auto* entry = history.newest(age);
      if (entry != nullptr && entry->channel_idx == _settings.channel) ++count;
    }
    return count;
  }
  template <typename History>
  bool scrollOlder(const History& history) { return _board.scrollOlder(boardCount(history)); }
  bool scrollOlder(unsigned count) { return _board.scrollOlder(count); }
  bool scrollNewer() { return _board.scrollNewer(); }
  bool isScrolled() const { return _board.scroll != 0; }
  void resetScroll() { _board.scroll = 0; }
  void messageAdded() { _board.messageAdded(); }

  template <typename History>
  void renderBoard(History& history, const char* channel_name) {
    char title[42], centre[18];
    snprintf(title, sizeof(title), "# %s", channel_name == nullptr ? "Channel" : channel_name);
    const unsigned count = boardCount(history);
    _board.clamp(count);
    if (_board.scroll != 0) snprintf(centre, sizeof(centre), "%u newer", _board.scroll);
    header(title, _board.scroll != 0 ? centre : nullptr);
    if (count == 0) {
      font(true); textCentre(_width / 2, 54, "Listening for messages");
      font(); textCentre(_width / 2, 72, "hold to browse / settings picks channel");
      footer(); return;
    }

    const bool large = _settings.text_large != 0;
    font(false, large);
    const int ascent = _font.getFontAscent();
    const int line_height = ascent - _font.getFontDescent() + (large ? 2 : 1);
    int y = bodyBottom();
    unsigned filtered_age = 0;
    for (size_t age = 0; age < history.count() && y >= bodyTop(); ++age) {
      const auto* entry = history.newest(age);
      if (entry == nullptr || entry->channel_idx != _settings.channel) continue;
      if (filtered_age++ < _board.scroll) continue;
      BoardMessageView message;
      parseBoardMessage(entry->origin, entry->message, entry->own_sent, message);
      char sender[64], body[192], timestamp[16];
      sanitizeText(sender, sizeof(sender), message.sender, message.sender_length);
      truncateCharacters(sender, nameCharacters(_settings));
      sanitizeText(body, sizeof(body), message.text, strlen(message.text));
      messageTime(timestamp, sizeof(timestamp), entry->heard_millis);
      font(true, large);
      int name_width = sender[0] == 0 ? 0 : textWidth(sender) + (entry->own_sent ? 9 : 5);
      // Long full names must leave room for the timestamp and message text.
      fitText(sender, _width / 2 - (entry->own_sent ? 9 : 5));
      name_width = sender[0] == 0 ? 0 : textWidth(sender) + (entry->own_sent ? 9 : 5);
      font(); const int time_width = textWidth(timestamp);
      font(false, large);
      Line lines[24];
      int line_count = wrap(body, _width - 10 - name_width - time_width,
                            _width - 4, lines, 24);
      if (line_count == 0) { lines[0] = {0, 0}; line_count = 1; }
      const int top = y - line_count * line_height + 1;
      bool shown = false;
      for (int i = 0; i < line_count; ++i) {
        const int line_top = top + i * line_height;
        if (line_top < bodyTop()) continue;
        const int baseline = line_top + ascent;
        int x = 2;
        if (i == 0) {
          if (sender[0] != 0) {
            font(true, large);
            if (entry->own_sent) {
              fill(x, line_top - 1, name_width - 3, line_height + 1);
              inverse(); text(x + 3, baseline, sender); normal();
            } else text(x, baseline, sender);
            x += name_width;
          }
          font(); textRight(_width - 2, baseline, timestamp);
          shown = true;
        }
        font(false, large);
        if (lines[i].length != 0) {
          textPart(x, baseline, body + lines[i].start, lines[i].length);
          shown = true;
        }
      }
      if (shown && _display->isOn()) history.markRead(entry);
      y = top - 5;
      if (y > bodyTop()) dots(2, _width - 2, y + 2);
    }
    footer();
  }

  void renderSettings(unsigned selected, bool editing, const char* channel_name = nullptr) {
    header("Settings", editing ? "editing" : nullptr);
    static const char* const names[] = {"Channel", "Text", "Names", "Screen", "Theme", "Return", "Clean", "Map zoom"};
    static const char* const idle[] = {"30 seconds", "1 minute", "5 minutes", "Never"};
    static const char* const clean[] = {"10 updates", "30 updates", "60 updates", "Manual"};
    for (unsigned row = 0; row < SETTINGS_COUNT; ++row) {
      const int y = bodyTop() + row * 11;
      if (row == selected && editing) { fill(1, y - 1, _width - 2, 11); inverse(); }
      else normal();
      font(row == selected && editing);
      text(4, y + 8, names[row]);
      char value[40];
      switch (row) {
        case 0:
          if (channel_name != nullptr && channel_name[0] != 0)
            sanitizeText(value, sizeof(value), channel_name, strlen(channel_name));
          else snprintf(value, sizeof(value), "Channel %u", _settings.channel);
          truncateCharacters(value, 19); break;
        case 1: snprintf(value, sizeof(value), "%s", _settings.text_large ? "Large" : "Small"); break;
        case 2:
          if (nameCharacters(_settings) == 0) snprintf(value, sizeof(value), "Full");
          else snprintf(value, sizeof(value), "%u characters", nameCharacters(_settings));
          break;
        case 3: snprintf(value, sizeof(value), "%s", _settings.flip ? "Flipped" : "Normal"); break;
        case 4: snprintf(value, sizeof(value), "%s", _settings.dark ? "Dark" : "Light"); break;
        case 5: snprintf(value, sizeof(value), "%s", idle[_settings.idle <= 3 ? _settings.idle : 1]); break;
        case 6: snprintf(value, sizeof(value), "%s", clean[_settings.refresh <= 3 ? _settings.refresh : 1]); break;
        default: snprintf(value, sizeof(value), "%u km", (unsigned)mapHeightKm(_settings)); break;
      }
      textRight(_width - 4, y + 8, value);
    }
    normal(); footer();
  }

  void renderMapChrome(unsigned actual_height_km = 0) {
    char range[24];
    snprintf(range, sizeof(range), "%u km", actual_height_km != 0
        ? actual_height_km : (unsigned)mapHeightKm(_settings));
    header("Map", range);
    footer();
  }
  void mapEmpty(const char* message) {
    font(true); textCentre(_width / 2, 54, message);
    font(); textCentre(_width / 2, 72, "Set location in the companion app");
  }
};

}  // namespace pocket
}  // namespace ui
}  // namespace mesh

#endif  // UI_POCKET_GUI
