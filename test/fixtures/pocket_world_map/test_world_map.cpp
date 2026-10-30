#include "helpers/ui/PocketWorldMap.h"
#include "helpers/ui/PocketWorldMapData.generated.h"
#include "helpers/ota/tinf/tinf.h"
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <initializer_list>
#include <stdio.h>
#include <string.h>

using namespace mesh::ui::pocket;

struct Canvas {
  static constexpr int width = 250, height = 91;
  bool pixels[height][width] = {};
  unsigned lines = 0;
  static void line(void* context, int x0, int y0, int x1, int y1) {
    Canvas& canvas = *static_cast<Canvas*>(context);
    assert(x0 >= 0 && x0 < width && x1 >= 0 && x1 < width);
    assert(y0 >= 0 && y0 < height && y1 >= 0 && y1 < height);
    ++canvas.lines;
    const int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    const int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    for (;;) {
      canvas.pixels[y0][x0] = true;
      if (x0 == x1 && y0 == y1) break;
      const int twice = error * 2;
      if (twice >= dy) { error += dy; x0 += sx; }
      if (twice <= dx) { error += dx; y0 += sy; }
    }
  }
  bool nearby(int x, int y, int radius) const {
    for (int yy = y - radius; yy <= y + radius; ++yy)
      for (int xx = x - radius; xx <= x + radius; ++xx)
        if (xx >= 0 && xx < width && yy >= 0 && yy < height && pixels[yy][xx]) return true;
    return false;
  }
};

static MapView view(double latitude, double longitude, double km = 200) {
  return {latitude, longitude, km, Canvas::width, Canvas::height};
}

static void testProjection() {
  int x, y;
  auto v = view(0, 180);
  assert(projectWorldPoint(v, 0, 180, x, y) && x == 125 && y == 45);
  int east, west;
  assert(projectWorldPoint(v, 0, -179.9, east, y));
  assert(projectWorldPoint(v, 0, 179.9, west, y));
  assert(east > 125 && west < 125 && east - west < 12);
  assert(!projectWorldPoint(v, 0, 0, x, y));
  assert(!projectWorldPoint(v, 0, 181, x, y));
  for (double pole : {-90.0, 90.0}) {
    v = view(pole, 0);
    assert(projectWorldPoint(v, pole, 170, x, y));
    assert(x == 125 && y == 45);
    assert(projectWorldPoint(v, pole > 0 ? 89.5 : -89.5, 90, x, y));
  }
  v = view(NAN, 0);
  assert(!projectWorldPoint(v, 0, 0, x, y));
  v = view(0, 0); v.width = 0;
  assert(!projectWorldPoint(v, 0, 0, x, y));
}

static void testFloatProjectionAccuracyAndWorldOverview() {
  constexpr double radians = 3.14159265358979323846 / 180.0;
  // Independent double-precision azimuthal reference. The device's float/FPU
  // implementation must stay within one pixel at close and continental zooms.
  for (double latitude : {-90.0, -78.0, -45.0, 0.0, 37.8, 78.0, 89.9, 90.0}) {
    for (double longitude : {-180.0, -122.5, 0.0, 180.0}) {
      for (double height : {5.0, 50.0, 200.0, 1000.0, 5000.0}) {
        const auto v = view(latitude, longitude, height);
        for (int row = -8; row <= 8; ++row) for (int col = -8; col <= 8; ++col) {
          const double lat = latitude + row * height / 111.195 / 16;
          if (lat < -90 || lat > 90) continue;
          double lon = longitude + col * height / 111.195 / 8 / fmax(0.01, cos(latitude * radians));
          lon = remainder(lon, 360.0);
          const double a = latitude * radians, b = lat * radians;
          const double delta = remainder((lon - longitude) * radians, 2 * 3.14159265358979323846);
          const double cosine = sin(a) * sin(b) + cos(a) * cos(b) * cos(delta);
          if (cosine < 0.00001) continue;
          const double distance = acos(fmin(1.0, cosine));
          const double factor = (distance < 1e-8 ? 6371.0088 : 6371.0088 * distance / sin(distance)) * 90 / height;
          const double px = 124.5 + factor * cos(b) * sin(delta);
          const double py = 45 - factor * (cos(a) * sin(b) - sin(a) * cos(b) * cos(delta));
          if (px < 1 || px > 248 || py < 1 || py > 89) continue;
          int x, y;
          assert(projectWorldPoint(v, lat, lon, x, y));
          assert(abs(x - int(lround(px))) <= 1 && abs(y - int(lround(py))) <= 1);
        }
      }
    }
  }
  const auto world = view(0, 0, 20000);
  // The full-world fallback must show every continent, not just one hemisphere.
  const double continents[][2] = {{37.8,-122.5}, {-23.5,-46.6}, {51.5,-0.1},
      {-33.9,18.4}, {35.7,139.7}, {-33.9,151.2}, {-90,0}, {90,0}};
  for (const auto& point : continents) {
    int x, y;
    assert(projectWorldPoint(world, point[0], point[1], x, y));
  }
  // A 179.9 -> 180.1 degree edge must end on both map edges and never draw a
  // horizontal line through the equator's centre.
  const uint8_t crossing[] = {2,0, 0xbc,0xbe,2,0, 0,0,0,0, 0x90,3,0};
  Canvas canvas;
  assert(renderWorldMapChunkForTest(world, crossing, sizeof(crossing), Canvas::line, &canvas));
  assert(canvas.lines == 2 && !canvas.pixels[45][125]);
  assert(canvas.nearby(36,45,1) && canvas.nearby(214,45,1));
}

static void testRealCoasts() {
  Canvas coast;
  auto v = view(37.8, -122.5);
  assert(renderWorldMap(v, Canvas::line, &coast));
  assert(coast.lines > 20);
  int x, y;
  assert(projectWorldPoint(v, 37.8, -122.5, x, y));
  assert(coast.nearby(x, y, 5));
  Canvas inland;
  assert(renderWorldMap(view(38.5, -98), Canvas::line, &inland));
  assert(inland.lines == 0);
  Canvas islands;
  assert(renderWorldMap(view(-16.5, 180, 500), Canvas::line, &islands));
  assert(islands.lines > 10);
  Canvas arctic;
  assert(renderWorldMap(view(78.2, 15.6), Canvas::line, &arctic));
  assert(arctic.lines > 20);
  for (auto polar : {view(90, 0, 2000), view(-90, 180, 2000), view(90, -180, 20000)}) {
    Canvas canvas;
    assert(renderWorldMap(polar, Canvas::line, &canvas));
    assert(canvas.lines > 0);
  }
  Canvas close;
  assert(renderWorldMap(view(-16.5, -180, 5), Canvas::line, &close));
  auto invalid = view(0, 0); invalid.height_km = 0;
  assert(!renderWorldMap(invalid, Canvas::line, &close));
  assert(!renderWorldMap(view(0, 0), nullptr, nullptr));
}

static void testChunksAndMalformedData() {
  unsigned decoded = 0;
  for (const auto& chunk : data::kChunks) {
    uint8_t scratch[data::kScratchBytes];
    unsigned size = sizeof(scratch);
    assert(chunk.offset + chunk.packed <= sizeof(data::kDeflate));
    assert(tinf_uncompress_exact(scratch, &size, data::kDeflate + chunk.offset, chunk.packed) == TINF_OK);
    assert(size == chunk.raw && size <= sizeof(scratch));
    Canvas canvas;
    assert(renderWorldMapChunkForTest(view(0, 0, 20000), scratch, size, Canvas::line, &canvas));
    // A truncation at every byte must fail unless it ends on a complete fragment.
    for (unsigned tail = 1; tail < 10 && tail < size; ++tail) {
      Canvas truncated;
      (void)renderWorldMapChunkForTest(view(0, 0), scratch, size - tail, Canvas::line, &truncated);
    }
    ++decoded;
  }
  assert(decoded == 32);
  assert(data::kRingCount == 1422);
  // Two points at 0,0 and 0.001,0.001 (zigzag delta 2,2).
  uint8_t valid[] = {2,0, 0,0,0,0, 0,0,0,0, 2,2};
  Canvas canvas;
  assert(renderWorldMapChunkForTest(view(0, 0), valid, sizeof(valid), Canvas::line, &canvas));
  assert(canvas.lines == 1);
  for (size_t size = 1; size < sizeof(valid); ++size)
    assert(!renderWorldMapChunkForTest(view(0, 0), valid, size, Canvas::line, &canvas));
  valid[0] = 1;
  assert(!renderWorldMapChunkForTest(view(0, 0), valid, sizeof(valid), Canvas::line, &canvas));
  valid[0] = 97;
  assert(!renderWorldMapChunkForTest(view(0, 0), valid, sizeof(valid), Canvas::line, &canvas));
  valid[0] = 2;
  valid[10] = valid[11] = 255;
  assert(!renderWorldMapChunkForTest(view(0, 0), valid, sizeof(valid), Canvas::line, &canvas));
  const uint8_t overflow[] = {2,0, 0,0,0,0, 0,0,0,0, 255,255,255,255,255,0};
  assert(!renderWorldMapChunkForTest(view(0, 0), overflow, sizeof(overflow), Canvas::line, &canvas));
}

int main() {
  testProjection();
  testFloatProjectionAccuracyAndWorldOverview();
  testRealCoasts();
  testChunksAndMalformedData();
  puts("world map projection, clipped raster, codec and parser checks passed");
}
