#include <helpers/ui/PocketGuiSettings.h>
#include <helpers/ui/UIScreen.h>
#include <cassert>
#include <initializer_list>

#define MAX_GROUP_CHANNELS 40

static uint32_t clock_millis = 123456;
uint32_t millis() { return clock_millis; }
struct Task {
  mesh::ui::pocket::Settings settings;
  int reader_opens = 0;
  mesh::ui::pocket::Settings& pocketSettings() { return settings; }
  unsigned pocketBoardCount() const { return 3; }
  void showReader() { ++reader_opens; }
  void showAlert(const char*, int) {}
};
struct Mesh {
  bool dual = true;
  bool isDualRadioActive() const { return dual; }
} the_mesh;

class HomeScreen : public UIScreen {
public:
  enum HomePage { FIRST, MAP, STATUS, SETTINGS, RECENT, RADIO, RADIO2, RADIO_STATUS, Count };
  struct Board {
    mesh::ui::pocket::BoardState state;
    bool scrollOlder(unsigned count) { return state.scrollOlder(count); }
    bool scrollNewer() { return state.scrollNewer(); }
    void resetScroll() { state.scroll = 0; }
  } _pocket;
  Task* _task;
  uint8_t _page = FIRST;
  bool _pocket_editing = false, _pocket_browsing = false, _pocket_zooming = false;
  bool _pocket_dirty = false, _dual_radio_enabled_seen = false;
  uint8_t _pocket_setting = 0, _radio_status_page = 0;
  uint32_t _pocket_last_input = 0, _radio_profile_page_started_at = 0;
  int save_count = 0, clean_count = 0;
  explicit HomeScreen(Task& task) : _task(&task) {}
  int render(DisplayDriver&) override { return 0; }
  bool flushPocketSettings() { ++save_count; _pocket_dirty = false; return true; }
  void displayForceClean() { ++clean_count; }
  void cyclePocketChannel(int direction) {
    _task->settings.channel = (_task->settings.channel + 40 + direction) % 40;
  }
  // @HOME_IMPLEMENTATION@
};

static void key(HomeScreen& home, uint8_t value) {
  assert(home.handleInput(static_cast<char>(value)));
  assert(home._pocket_last_input == clock_millis);
}

int main() {
  Task task;
  HomeScreen home(task);
  key(home, KEY_ENTER);
  assert(home._page == HomeScreen::FIRST && home._pocket_browsing);
  key(home, KEY_NEXT);
  assert(home._pocket.state.scroll == 1 && home._page == HomeScreen::FIRST);
  key(home, KEY_PREV);
  assert(home._pocket.state.scroll == 0);
  key(home, KEY_DOWN);
  assert(task.settings.channel == 1);
  key(home, KEY_UP);
  assert(task.settings.channel == 0);
  key(home, KEY_ENTER);
  assert(!home._pocket_browsing);
  key(home, KEY_NEXT);
  assert(home._page == HomeScreen::MAP);
  key(home, KEY_ENTER);
  assert(home._pocket_zooming);
  key(home, KEY_NEXT);
  assert(task.settings.map_zoom == 4 && home._pocket_dirty);
  key(home, KEY_PREV);
  assert(task.settings.map_zoom == 3);
  key(home, KEY_ENTER);
  assert(!home._pocket_zooming && !home._pocket_dirty);
  key(home, KEY_NEXT);
  key(home, KEY_NEXT);
  assert(home._page == HomeScreen::SETTINGS);
  key(home, KEY_ENTER);
  assert(home._pocket_editing);
  key(home, KEY_PREV);
  assert(home._pocket_setting == 1);
  key(home, KEY_NEXT);
  assert(task.settings.text_large == 1 && home._pocket_dirty);
  home._pocket_setting = 4;
  key(home, KEY_NEXT);
  assert(task.settings.dark == 1 && home.clean_count == 1);
  key(home, KEY_ENTER);
  assert(!home._pocket_editing && !home._pocket_dirty);
  key(home, KEY_PREV);
  assert(home._page == HomeScreen::STATUS);
  key(home, KEY_ENTER);
  assert(home._radio_status_page == 1 && task.reader_opens == 0);

  // Pairing can interrupt any editing/browsing mode. Returning to the first
  // page saves settings and leaves the next click free to navigate normally.
  for (const auto interrupted : {HomeScreen::SETTINGS, HomeScreen::MAP, HomeScreen::FIRST}) {
    home._page = interrupted;
    home._pocket_editing = home._pocket_browsing = home._pocket_zooming = true;
    home._pocket_dirty = true;
    home._pocket.state.scroll = 2;
    home._pocket_last_input = 0;
    const int saves = home.save_count;
    clock_millis += 1000;
    home.showFirstPage();
    assert(home._page == HomeScreen::FIRST && home.save_count == saves + 1);
    assert(!home._pocket_editing && !home._pocket_browsing && !home._pocket_zooming);
    assert(!home._pocket_dirty && home._pocket.state.scroll == 0);
    assert(home._pocket_last_input == clock_millis);
    key(home, KEY_NEXT);
    assert(home._page == HomeScreen::MAP);
  }

  // The existing Network-page hold remains the Reader action in the new GUI.
  home._page = HomeScreen::RADIO;
  key(home, KEY_ENTER);
  assert(task.reader_opens == 1 && home._page == HomeScreen::RADIO);
  home._page = HomeScreen::RADIO2;
  key(home, KEY_ENTER);
  assert(task.reader_opens == 2 && home._page == HomeScreen::RADIO2);
  home._page = HomeScreen::RADIO_STATUS;
  key(home, KEY_ENTER);
  assert(home._radio_status_page == 2 && task.reader_opens == 2);
  the_mesh.dual = false;
  home._page = HomeScreen::RADIO;
  key(home, KEY_NEXT);
  assert(home._page == HomeScreen::FIRST);
}
