#include <helpers/ui/PocketGuiSettings.h>
#include <helpers/ui/PocketWorldMap.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

using std::isfinite;

struct ContactInfo {
  int32_t gps_lat, gps_lon;
  char name[32];
};

struct Mesh {
  std::vector<ContactInfo> contacts;
  struct Iterator {
    size_t next = 0;
    bool hasNext(Mesh* mesh, ContactInfo& contact) {
      if (next >= mesh->contacts.size()) return false;
      contact = mesh->contacts[next++];
      return true;
    }
  };
  Iterator startContactsIterator() { return {}; }
} the_mesh;

struct Sensors {
  double node_lat = 0, node_lon = 0;
} sensors;

namespace mesh { namespace ui { namespace pocket {

static MapView rendered_view{};
static unsigned renders = 0;

bool renderWorldMap(const MapView& view, MapLine line, void* context) {
  rendered_view = view;
  ++renders;
  line(context, 0, 0, view.width - 1, view.height - 1);
  return true;
}

bool projectWorldPoint(const MapView& view, double, double, int& x, int& y) {
  assert(view.height_km == rendered_view.height_km);
  x = 10;
  y = 12;
  return true;
}

class PocketGui {
public:
  std::vector<std::string> labels;
  std::string hint;
  Settings _settings;
  unsigned markers = 0, own_markers = 0, range = 0;
  int width() const { return 250; }
  int bodyTop() const { return 20; }
  int bodyBottom() const { return 102; }
  void line(int, int y0, int, int y1) {
    assert(y0 == bodyTop() && y1 == bodyBottom() - 1);
  }
  void label(int, int, const char* text) { labels.emplace_back(text); }
  void marker(int, int, bool own = false) {
    ++markers;
    if (own) ++own_markers;
  }
  void header(const char* title, const char* range_label) {
    assert(std::strcmp(title, "Map") == 0);
    assert(std::sscanf(range_label, "%u km", &range) == 1);
  }
  void footer(const char* footer_hint) {
    assert(footer_hint != nullptr);
    hint = footer_hint;
  }
  // @MAP_CHROME_IMPLEMENTATION@
};

}}}

struct Task {
  mesh::ui::pocket::Settings settings;
  const mesh::ui::pocket::Settings& pocketSettings() const { return settings; }
};

class HomeScreen {
public:
  Task* _task;
  mesh::ui::pocket::PocketGui _pocket;
  bool _pocket_map_located = false;
  bool _pocket_zooming = false, _pocket_dirty = false;
  unsigned save_count = 0, clean_count = 0;
  explicit HomeScreen(Task& task) : _task(&task) {}
  bool flushPocketSettings() { ++save_count; _pocket_dirty = false; return true; }
  void displayForceClean() { ++clean_count; }
  // @MAP_IMPLEMENTATION@
};

static void checkView(const HomeScreen& home, double latitude, double longitude,
                      unsigned height, bool located) {
  using namespace mesh::ui::pocket;
  assert(std::fabs(rendered_view.latitude - latitude) < 0.000001);
  assert(std::fabs(rendered_view.longitude - longitude) < 0.000001);
  assert(rendered_view.height_km == height && home._pocket.range == height);
  assert(rendered_view.width == 250 && rendered_view.height == 82);
  assert(home._pocket_map_located == located);
  assert(home._pocket.hint == (!located ? "click next  2x back"
      : home._pocket_zooming ? "1x zoom in  2x out  hold done"
      : "click next  2x back  hold zoom"));
}

int main() {
  using namespace mesh::ui::pocket;
  Task task;
  HomeScreen home(task);
  home.renderPocketMap();
  assert(renders == 1 && home._pocket.markers == 0);
  checkView(home, 0, 0, 20000, false);
  assert(home.clean_count == 0);
  assert(home._pocket.labels.back() == "World / no node locations");

  // Even a saved 5 km preference must show the complete world without a
  // location. Rendering the fallback must not overwrite that preference.
  the_mesh.contacts = {{0, 0, "Unset"}, {91000000, 1000000, "Invalid"}};
  for (unsigned zoom = 0; zoom < 10; ++zoom) {
    task.settings.map_zoom = zoom;
    home.renderPocketMap();
    checkView(home, 0, 0, 20000, false);
    assert(task.settings.map_zoom == zoom);
    assert(home._pocket.markers == 0);
    assert(home._pocket.labels.back() == "World / no node locations");
    assert(home.clean_count == 0);
  }

  // The first frame with an own location resumes 5 km and immediately shows
  // the zoom hint, even though the previous frame had no location.
  task.settings.map_zoom = 8;
  the_mesh.contacts.clear();
  sensors = {47.5, -122.25};
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 5, true);
  assert(home._pocket.own_markers == 1);
  assert(home.clean_count == 1);

  home._pocket_zooming = home._pocket_dirty = true;
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 5, true);
  assert(home._pocket_zooming && home._pocket_dirty && home.save_count == 0);
  assert(home.clean_count == 1);

  // Losing the location while zooming saves the pending preference once and
  // releases the controls for page navigation. The footer changes this frame.
  sensors = {0, 0};
  home.renderPocketMap();
  checkView(home, 0, 0, 20000, false);
  assert(task.settings.map_zoom == 8 && !home._pocket_zooming && !home._pocket_dirty);
  assert(home.save_count == 1);
  assert(home.clean_count == 2);
  home.renderPocketMap();
  assert(home.save_count == 1 && home.clean_count == 2);
  home._pocket_zooming = true;
  home.renderPocketMap();
  assert(!home._pocket_zooming && home.save_count == 1 && home.clean_count == 2);

  // With no own position, the first valid contact supplies the center; later
  // contacts do not move it. The saved 5 km range resumes for this case too.
  home._pocket.markers = home._pocket.own_markers = 0;
  sensors = {std::numeric_limits<double>::quiet_NaN(), 999};
  the_mesh.contacts = {{0, 0, "Unset"}, {91000000, 1000000, "Invalid"},
                      {37500000, 139100000, "First"},
                      {48000000, -120000000, "Later"}};
  home.renderPocketMap();
  checkView(home, 37.5, 139.1, 5, true);
  assert(home._pocket.markers == 2 && home._pocket.own_markers == 0);
  assert(home.clean_count == 3);

  sensors = {47.5, -122.25};
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 5, true);
  assert(home._pocket.own_markers == 1);
  assert(home.clean_count == 3);

  // Auto still chooses a 200 km local view and the world fallback.
  task.settings = Settings{};
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 200, true);
  sensors = {0, 0};
  the_mesh.contacts.clear();
  home.renderPocketMap();
  checkView(home, 0, 0, 20000, false);
  assert(home.clean_count == 4);
}
