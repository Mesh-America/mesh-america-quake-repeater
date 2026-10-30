#include <helpers/ui/CompanionMessageHistory.h>
#include <helpers/ui/DisplayPowerPolicy.h>
#include <cassert>
#include <cstring>

#define UI_MSG_PREVIEW_SIZE 161
#define MAX_GROUP_CHANNELS 40
#define KEY_UP 0xB5
#define KEY_DOWN 0xB6
#define MESH_DEBUG_PRINTLN(...)

static uint32_t now_millis = 12345;
uint32_t millis() { return now_millis; }
uint64_t companionMessageNowMillis() { return now_millis; }
struct Screen { virtual ~Screen() = default; };
struct Display {
  bool on = true;
  int wakes = 0;
  bool isOn() const { return on; }
  void wake(mesh::ui::DisplayWake) { ++wakes; }
};

struct MsgPreviewScreen : Screen {
  mesh::ui::CompanionMessageHistory<32, UI_MSG_PREVIEW_SIZE> history;
  bool selected = false;
  void addPreview(uint8_t, const char* sender, const char* text, int channel,
                  const char* channel_name, int queue_index, bool select) {
    selected = select;
    history.add(now_millis, channel, channel_name, sender, text, queue_index);
  }
  // @ADD_SENT@
};
struct HomeScreen : Screen {
  bool board = true;
  int message_hooks = 0;
  bool isPocketBoard() const { return board; }
  void pocketMessageAdded(int) { ++message_hooks; }
};

class UITask {
public:
  Screen *home, *msg_preview, *reader, *curr;
  Display* _display;
  int _msgcount = 0, screen_changes = 0, buzzer_changes = 0;
  uint32_t _next_refresh = 0;
  bool connected = false, pairing = false, allow_wake = true;
  bool _deferred_msg_preview = false;
  UITask(HomeScreen& h, MsgPreviewScreen& m, Screen& r, Display& d)
      : home(&h), msg_preview(&m), reader(&r), curr(&h), _display(&d) {}
  bool hasConnection() const { return connected; }
  bool isPairingScreenActive() const { return pairing; }
  bool isReaderActive() const { return curr == reader; }
  bool shouldWakeDisplayForMessage() const { return allow_wake; }
  void setCurrScreen(Screen* screen) { curr = screen; ++screen_changes; }
  char checkDisplayOn(char key) { return key; }
  void toggleBuzzer() { ++buzzer_changes; }
  void newMsg(uint8_t path_len, const char* from, const char* text, int count,
              int channel, const char* channel_name, int queue_index);
  void channelMessageSent(int channel, const char* channel_name, const char* sender,
                          const char* text, size_t length);
  char handleMultiClick(char key, bool backwards);
};

// @TASK_METHODS@

int main() {
  HomeScreen home;
  MsgPreviewScreen preview;
  Screen reader;
  Display display;
  UITask task(home, preview, reader, display);
  auto receive = [&](int channel = 0) {
    task.newMsg(1, "Channel Public", "Alice: received", 7, channel, "Public", 3);
  };

  // A live-board channel arrival updates history without stealing the board.
  receive();
  assert(task.curr == &home && task.screen_changes == 0);
  assert(preview.history.count() == 1 && home.message_hooks == 1);
  assert(!task._deferred_msg_preview && task._msgcount == 7);
  assert(preview.selected && display.wakes == 1 && task._next_refresh == now_millis);

  // Connected apps, the pairing PIN and the Reader keep their existing policy.
  task.connected = true;
  receive();
  assert(task.curr == &home && !preview.selected && !task._deferred_msg_preview);
  task.connected = false;
  task.pairing = true;
  receive();
  assert(task.curr == &home && task._deferred_msg_preview);
  task.pairing = false;
  task.curr = &reader;
  receive();
  assert(task.curr == &reader && task._deferred_msg_preview);
  task.curr = &home;
  home.board = false;
  receive();
  assert(task.curr == &preview);
  task.curr = &home;
  home.board = true;
  receive(-1);
  assert(task.curr == &preview); // a direct message retains its normal preview

  const int previous_wakes = display.wakes;
  task.allow_wake = false;
  receive();
  assert(display.wakes == previous_wakes);

  // The outbound app buffer is length-delimited, not necessarily terminated.
  const char raw[] = {'o', 'w', 'n'};
  task.curr = &reader;
  task.channelMessageSent(0, "Public", "Self", raw, sizeof(raw));
  assert(task.curr == &reader);
  const auto* sent = preview.history.newest(0);
  assert(sent->own_sent && !sent->unread && sent->queue_index == -1);
  assert(std::strcmp(sent->message, "own") == 0);
  const size_t previous_count = preview.history.count();
  task.channelMessageSent(-1, "Public", "Self", raw, sizeof(raw));
  task.channelMessageSent(40, "Public", "Self", raw, sizeof(raw));
  assert(preview.history.count() == previous_count);
  char long_text[200];
  std::memset(long_text, 'x', sizeof(long_text));
  task.channelMessageSent(0, "Public", "Self", long_text, sizeof(long_text));
  assert(std::strlen(preview.history.newest(0)->message) == UI_MSG_PREVIEW_SIZE - 1);

  task.curr = &home;
  assert(static_cast<uint8_t>(task.handleMultiClick(0, false)) == KEY_DOWN);
  assert(static_cast<uint8_t>(task.handleMultiClick(0, true)) == KEY_UP);
  assert(task.buzzer_changes == 0);
  home.board = false;
  assert(task.handleMultiClick(0, false) == 0 && task.buzzer_changes == 1);
}
