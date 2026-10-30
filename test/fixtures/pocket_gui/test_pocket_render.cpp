#include <examples/companion_radio/ui-new/PocketGui.h>
#include <helpers/ui/CompanionMessageHistory.h>
#include <cassert>
#include <cstring>
#include <initializer_list>

using namespace mesh::ui::pocket;
using History = mesh::ui::CompanionMessageHistory<32, 161>;

static void channelBoard() {
  Settings settings;
  Frame frame;
  frame.now = 1735689600UL + 30 * 60;
  frame.heard_millis = 120000;
  frame.tz_offset = 5.75f;
  frame.battery_percent = 101;
  frame.page_count = 11;
  frame.connection = "BLE+USB";
  GxEPDDisplay display;
  PocketGui gui;
  History history;
  history.add(60000, 0, "Public", "Ch 0 Public [1h]:", "Alice: hello everyone");
  history.add(100000, 2, "Private", "Ch 2 Private [1h]:", "secret sender: hidden");
  history.add(120000, 0, "Public", "Self", "outgoing", -1, true);
  history.add(120000, -1, "", "Bob [direct]:", "direct hidden");
  gui.begin(display, settings, frame);
  assert(gui.boardCount(history) == 2);
  gui.renderBoard(history, "Public");
  assert(display.gfx().contains("Alice"));
  assert(display.gfx().contains("Self"));
  assert(display.gfx().contains("outgoing"));
  assert(!display.gfx().contains("secret sender"));
  assert(!display.gfx().contains("direct hidden"));
  assert(display.gfx().contains("100%"));
  // UTC 00:30 plus 05:45 Nepal offset. The previous-minute message gets 06:14.
  assert(display.gfx().contains("06:15"));
  assert(display.gfx().contains("06:14"));
  bool sent_inverted = false;
  for (const auto& text : display.gfx().labels)
    if (text.value == "Self") sent_inverted = text.foreground == GxEPD_WHITE;
  assert(sent_inverted);

  display.resetHash();
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  const uint32_t first_hash = display.hash;
  display.resetHash();
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(display.hash == first_hash); // unchanged content skips physical redraw

  assert(gui.scrollOlder(history) && gui.isScrolled());
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(display.gfx().contains("1 newer") && !display.gfx().contains("Self"));
  history.add(120000, 0, "Public", "Ch 0 Public [1h]:", "Carol: new message");
  gui.messageAdded();
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(display.gfx().contains("2 newer") && display.gfx().contains("Alice"));
  assert(!display.gfx().contains("Carol"));
  gui.resetScroll();
  assert(!gui.isScrolled());

  // Negative fractional offsets also cross midnight correctly.
  frame.tz_offset = -3.5f;
  gui.begin(display, settings, frame);
  gui.renderMapChrome();
  gui.header("Map");
  assert(display.gfx().contains("21:00"));

  // A message received before Arduino millis() wrapped still retains its
  // actual age, rather than being relabelled as newly received.
  history.clear();
  history.add(UINT32_MAX - 59999U, 0, "Public", "Self", "before rollover", -1, true);
  frame.now = 0;
  frame.heard_millis = 1000;
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(display.gfx().contains("1m"));
}

static void screenBounds() {
  History history;
  char body[161];
  std::memset(body, 'W', sizeof(body) - 1);
  body[sizeof(body) - 1] = 0;
  history.add(0, 0, "Public", "ExtremelyLongSenderNameWWWWWWWWWWWWWWWWWWWW", body, -1, true);
  history.add(0, 0, "Public", "Ch 0 Public [1h]:", "\xc3\x89lise: UTF-8 caf\xc3\xa9 message with words and a long paragraph that wraps onto several rows");
  Frame frame;
  frame.now = 1735689600UL;
  frame.battery_percent = -1;
  frame.hint = "click next / 2x back";
  for (unsigned large : {0U, 1U})
    for (unsigned flip : {0U, 1U})
      for (unsigned dark : {0U, 1U})
        for (unsigned name : {0U, 1U, 2U, 3U}) {
          Settings settings;
          settings.text_large = large;
          settings.flip = flip;
          settings.dark = dark;
          settings.name_len = name;
          PocketGui gui;
          GxEPDDisplay display;
          gui.begin(display, settings, frame);
          gui.renderBoard(history, "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW");
          assert(display.gfx().rotation == (flip ? 1 : 3));
          for (unsigned row = 0; row < SETTINGS_COUNT; ++row) {
            gui.begin(display, settings, frame);
            gui.renderSettings(row, true, "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW");
          }
          gui.begin(display, settings, frame);
          gui.renderMapChrome();
          gui.mapEmpty("No valid position");
        }
  PocketGui gui;
  GxEPDDisplay display;
  Settings settings;
  settings.channel = 39;
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Empty");
  assert(gui.boardCount(history) == 0);
  assert(display.gfx().contains("Listening for messages"));

  // Display hints may be supplied by navigation. They must remain inside the
  // screen even if a future page supplies more text than fits on one line.
  frame.hint = "An extremely long footer WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW";
  gui.begin(display, settings, frame);
  gui.renderMapChrome();

  history.clear();
  std::memset(body, 'W', sizeof(body) - 1);
  std::strcpy(body + sizeof(body) - 7, " END42");
  history.add(0, 0, "Public", "\xc3\x89lise", body, -1, true);
  settings.channel = 0;
  settings.text_large = 1;
  settings.name_len = 3;
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  bool tail_visible = false;
  for (const auto& text : display.gfx().labels)
    if (text.value.find("END42") != std::string::npos) tail_visible = true;
  assert(tail_visible);
}

static void measuredLabels() {
  Settings settings;
  Frame frame;
  GxEPDDisplay display;
  PocketGui gui;
  gui.begin(display, settings, frame);
  gui.label(4, 30, "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW", true);
  assert(display.gfx().labels.size() == 1);
  const auto& broad = display.gfx().labels.front();
  assert(broad.width <= 246 && broad.value.size() < 31 && broad.bold);
  gui.text(4, 45, "Normal again");
  assert(!display.gfx().labels.back().bold);
  gui.label(240, 60, "\xc3\x89WWWWWWWWW", true);
  assert(display.gfx().labels.back().value == "\xc3\x89");
  gui.text(4, 75, "Normal again");
  assert(!display.gfx().labels.back().bold);
  const size_t previous = display.gfx().labels.size();
  gui.label(-1, 90, "outside", true);
  gui.label(250, 90, "outside", true);
  gui.label(4, 90, nullptr, true);
  assert(display.gfx().labels.size() == previous);
  gui.text(4, 105, "Normal after invalid label");
  assert(!display.gfx().labels.back().bold);
  gui.begin(display, settings, frame);
  gui.renderMapChrome(20000);
  assert(display.gfx().contains("20000 km"));
  gui.begin(display, settings, frame);
  gui.renderMapChrome();
  assert(display.gfx().contains("200 km"));
}

static void readOnlyVisibleEntries() {
  Settings settings;
  Frame frame;
  GxEPDDisplay display;
  PocketGui gui;
  History history;
  history.add(0, 0, "Public", "Ch 0 Public", "Alice: oldest hidden", 0);
  history.add(0, 0, "Public", "Ch 0 Public", "Bob: older hidden", 1);
  history.add(0, 1, "Private", "Ch 1 Private", "Carol: other channel", 2);
  char long_body[161];
  std::memset(long_body, 'W', sizeof(long_body) - 1);
  long_body[sizeof(long_body) - 1] = 0;
  history.add(0, 0, "Public", "Ch 0 Public", long_body, 3);
  settings.text_large = 1;
  gui.begin(display, settings, frame);
  assert(history.unreadCount() == 4);
  gui.renderBoard(history, "Public");
  assert(!history.newest(0)->unread); // the long message's visible tail counts
  assert(history.newest(1)->unread);  // another channel
  assert(history.newest(2)->unread && history.newest(3)->unread); // above the viewport
  for (unsigned age = 0; age < history.count(); ++age)
    assert(history.newest(age)->queue_index == static_cast<int>(3 - age));

  assert(gui.scrollOlder(history));
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(!history.newest(2)->unread && !history.newest(3)->unread);
  assert(history.newest(1)->unread && history.unreadCount() == 1);
  assert(history.newest(0)->queue_index == 3); // reading never consumes app delivery

  // Merely composing a frame while the panel is off does not mark it read.
  history.clear();
  history.add(0, 0, "Public", "Ch 0 Public", "Alice: sleeping panel", 7);
  gui.resetScroll();
  display.on = false;
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(history.newest(0)->unread && history.newest(0)->queue_index == 7);
  display.on = true;
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(!history.newest(0)->unread && history.newest(0)->queue_index == 7);

  // Scrolling to an older entry does not acknowledge the newer skipped one.
  history.clear();
  history.add(0, 0, "Public", "Ch 0 Public", "Alice: older", 1);
  history.add(0, 0, "Public", "Ch 0 Public", "Bob: newer", 2);
  gui.resetScroll();
  assert(gui.scrollOlder(history));
  gui.begin(display, settings, frame);
  gui.renderBoard(history, "Public");
  assert(history.newest(0)->unread && !history.newest(1)->unread);
  assert(history.newest(0)->queue_index == 2 && history.newest(1)->queue_index == 1);
}

int main() {
  channelBoard();
  screenBounds();
  measuredLabels();
  readOnlyVisibleEntries();
}
