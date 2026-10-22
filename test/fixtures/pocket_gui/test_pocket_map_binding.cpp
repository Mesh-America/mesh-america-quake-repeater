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
  void renderMapChrome(unsigned height) { range = height; }
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
  explicit HomeScreen(Task& task) : _task(&task) {}
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
}

int main() {
  using namespace mesh::ui::pocket;
  Task task;
  HomeScreen home(task);
  home.renderPocketMap();
  assert(renders == 1 && home._pocket.markers == 0);
  checkView(home, 0, 0, 20000, false);
  assert(home._pocket.labels.back() == "World / no node locations");

  // Executing the actual page binding is essential: valid zoom settings used
  // to be discarded here whenever no contact or self location was available.
  const unsigned heights[] = {20000, 5000, 1000, 200, 100, 50, 20, 10, 5};
  the_mesh.contacts = {{0, 0, "Unset"}, {91000000, 1000000, "Invalid"}};
  for (unsigned zoom = 0; zoom < 9; ++zoom) {
    task.settings.map_zoom = zoom;
    home.renderPocketMap();
    checkView(home, 0, 0, heights[zoom], false);
    assert(home._pocket.markers == 0);
    assert(home._pocket.labels.back() == (zoom == 0
        ? "World / no node locations" : "no node locations"));
  }

  task.settings = Settings{};
  assert(zoomMap(task.settings, true, home._pocket_map_located));
  home.renderPocketMap();
  checkView(home, 0, 0, 5000, false);
  assert(zoomMap(task.settings, false, home._pocket_map_located));
  home.renderPocketMap();
  checkView(home, 0, 0, 20000, false);

  // Auto uses the real local center when it is known and returns to the
  // overview if that location disappears. It never invents a node at 0,0.
  task.settings = Settings{};
  the_mesh.contacts.clear();
  sensors = {47.5, -122.25};
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 200, true);
  assert(home._pocket.own_markers == 1);
  sensors = {0, 0};
  home.renderPocketMap();
  checkView(home, 0, 0, 20000, false);
  assert(home._pocket.own_markers == 1);

  // With no own position, the first valid contact supplies the center; later
  // contacts do not move it. Invalid or unset contact locations are skipped.
  sensors = {std::numeric_limits<double>::quiet_NaN(), 999};
  the_mesh.contacts = {{0, 0, "Unset"}, {91000000, 1000000, "Invalid"},
                      {37500000, 139100000, "First"},
                      {48000000, -120000000, "Later"}};
  home.renderPocketMap();
  checkView(home, 37.5, 139.1, 200, true);
  assert(home._pocket.markers == 3 && home._pocket.own_markers == 1);

  sensors = {47.5, -122.25};
  home.renderPocketMap();
  checkView(home, 47.5, -122.25, 200, true);
  assert(home._pocket.own_markers == 2);
}
