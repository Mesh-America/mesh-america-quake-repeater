#include "PocketWorldMap.h"
#include "PocketGuiConfig.h"

#if UI_POCKET_GUI || defined(POCKET_WORLD_MAP_TEST)

#include "PocketWorldMapData.generated.h"
#include "../ota/tinf/tinf.h"
#include <math.h>

namespace mesh { namespace ui { namespace pocket {
namespace {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kRadians = kPi / 180.0f;
constexpr float kEarthKm = 6371.0088f;

struct Projection {
  float latitude, longitude, sine, cosine, pixels_per_km, radius;
  int width, height;
  bool global;
};

bool makeProjection(const MapView& view, Projection& p) {
  if (!isfinite(view.latitude) || !isfinite(view.longitude) || !isfinite(view.height_km)
      || view.latitude < -90.0 || view.latitude > 90.0 || view.longitude < -180.0
      || view.longitude > 180.0 || view.height_km < 1.0 || view.height_km > 20000.0
      || view.width < 2 || view.height < 2 || view.width > 4096 || view.height > 4096) return false;
  p.latitude = float(view.latitude) * kRadians;
  p.longitude = float(view.longitude) * kRadians;
  p.width = view.width;
  p.height = view.height;
  p.global = view.height_km == 20000.0;
  if (p.global) {
    // The overview includes every longitude and latitude, independent of the
    // local centre's latitude. Preserve 2:1 map proportions with blank margins.
    p.pixels_per_km = fminf((view.width - 1) / 360.0f, (view.height - 1) / 180.0f);
    return true;
  }
  p.sine = sinf(p.latitude);
  p.cosine = fabsf(float(view.latitude)) == 90.0f ? 0.0f : cosf(p.latitude);
  p.pixels_per_km = (view.height - 1) / float(view.height_km);
  p.radius = hypotf(view.width - 1, view.height - 1) * 0.5f / p.pixels_per_km / kEarthKm;
  return true;
}

bool project(const Projection& p, float latitude, float longitude, float& x, float& y) {
  if (!isfinite(latitude) || !isfinite(longitude) || latitude < -90.0f || latitude > 90.0f) return false;
  if (p.global) {
    float degrees = longitude - p.longitude / kRadians;
    while (degrees > 180.0f) degrees -= 360.0f;
    while (degrees < -180.0f) degrees += 360.0f;
    x = (p.width - 1) * 0.5f + degrees * p.pixels_per_km;
    y = (p.height - 1) * 0.5f - latitude * p.pixels_per_km;
    return true;
  }
  const float lat = latitude * kRadians;
  float delta = longitude * kRadians - p.longitude;
  // Decoded longitudes are bounded to +/-540 degrees, so at most two wraps.
  while (delta > kPi) delta -= 2.0f * kPi;
  while (delta < -kPi) delta += 2.0f * kPi;
  const float sin_lat = sinf(lat);
  const float cos_lat = fabsf(latitude) == 90.0f ? 0.0f : cosf(lat);
  const float cos_delta = cosf(delta);
  float cos_distance = p.sine * sin_lat + p.cosine * cos_lat * cos_delta;
  if (cos_distance > 1.0f) cos_distance = 1.0f;
  // At the far hemisphere the azimuthal singularity can join unrelated edges.
  // The Pocket's local map never needs that hemisphere to cover its viewport.
  if (cos_distance < 0.0f) return false;
  // c/sin(c) has a stable expansion at zero. It avoids acosf cancellation
  // (and two transcendental calls) for nearby nodes and coastline vertices.
  const float scale = cos_distance > 0.9999f
      ? kEarthKm * (1.0f + (1.0f - cos_distance) / 3.0f)
      : kEarthKm * acosf(cos_distance) / sqrtf(1.0f - cos_distance * cos_distance);
  x = (p.width - 1) * 0.5f + scale * cos_lat * sinf(delta) * p.pixels_per_km;
  y = (p.height - 1) * 0.5f - scale * (p.cosine * sin_lat - p.sine * cos_lat * cos_delta) * p.pixels_per_km;
  return isfinite(x) && isfinite(y);
}

// Conservative spherical-cap/bounding-box test; it may decode extra chunks,
// but never discards visible land at the antimeridian or either pole.
bool visibleChunk(const Projection& p, const data::Chunk& chunk) {
  if (p.global) return true;
  const float latitude = p.latitude / kRadians;
  const float degrees = p.radius / kRadians + 0.01f;
  if (chunk.north * 0.001f < latitude - degrees || chunk.south * 0.001f > latitude + degrees) return false;
  if (p.radius >= kPi * 0.5f || latitude + degrees >= 90.0f || latitude - degrees <= -90.0f) return true;
  const float ratio = sinf(p.radius) / p.cosine;
  if (ratio >= 1.0f || ratio <= -1.0f) return true;
  const float half_longitude = fabsf(asinf(ratio)) / kRadians + 0.01f;
  const float center = p.longitude / kRadians;
  // Source fragments are unwrapped; test adjacent copies of the view.
  for (int copy = -1; copy <= 1; ++copy) {
    const float longitude = center + copy * 360.0f;
    if (chunk.east * 0.001f >= longitude - half_longitude
        && chunk.west * 0.001f <= longitude + half_longitude) return true;
  }
  return false;
}

bool clipAxis(float start, float delta, float minimum, float maximum, float& first, float& last) {
  if (delta == 0.0f) return start >= minimum && start <= maximum;
  float a = (minimum - start) / delta, b = (maximum - start) / delta;
  if (a > b) { const float swap = a; a = b; b = swap; }
  if (a > first) first = a;
  if (b < last) last = b;
  return first <= last;
}

void drawClipped(const Projection& p, float ax, float ay, float bx, float by,
                 MapLine line, void* context) {
  float first = 0.0f, last = 1.0f;
  const float margin = p.global ? ((p.width - 1) * 0.5f - 180.0f * p.pixels_per_km) : 0.0f;
  if (!clipAxis(ax, bx - ax, margin, p.width - 1 - margin, first, last)
      || !clipAxis(ay, by - ay, 0.0f, p.height - 1, first, last)) return;
  const int x0 = static_cast<int>(lroundf(ax + first * (bx - ax)));
  const int y0 = static_cast<int>(lroundf(ay + first * (by - ay)));
  const int x1 = static_cast<int>(lroundf(ax + last * (bx - ax)));
  const int y1 = static_cast<int>(lroundf(ay + last * (by - ay)));
  line(context, x0, y0, x1, y1);
}

void drawSegment(const Projection& p, float ax, float ay, float bx, float by,
                 MapLine line, void* context) {
  if (p.global) {
    const float span = 360.0f * p.pixels_per_km;
    if (fabsf(bx - ax) > span * 0.5f) {
      // Split a seam crossing at the two map edges, never across the middle.
      if (bx > ax) ax += span;
      else bx += span;
      drawClipped(p, ax, ay, bx, by, line, context);
      drawClipped(p, ax - span, ay, bx - span, by, line, context);
      return;
    }
  }
  drawClipped(p, ax, ay, bx, by, line, context);
}

uint16_t read16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
int32_t read32(const uint8_t* p) {
  return static_cast<int32_t>(uint32_t(p[0]) | (uint32_t(p[1]) << 8)
                             | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24));
}

bool readDelta(const uint8_t*& cursor, const uint8_t* end, int32_t& delta) {
  uint32_t value = 0;
  // Coordinates fit signed 32-bit, but a map delta needs at most 21 bits.
  for (unsigned shift = 0; shift < 28; shift += 7) {
    if (cursor == end) return false;
    const uint8_t byte = *cursor++;
    value |= uint32_t(byte & 127) << shift;
    if (!(byte & 128)) {
      delta = (value & 1) ? -static_cast<int32_t>((value >> 1) + 1) : static_cast<int32_t>(value >> 1);
      return true;
    }
  }
  return false;
}

bool drawChunk(const Projection& p, const uint8_t* bytes, size_t size, MapLine line, void* context) {
  const uint8_t* cursor = bytes;
  const uint8_t* end = bytes + size;
  while (cursor != end) {
    if (size_t(end - cursor) < 10) return false;
    const unsigned count = read16(cursor);
    int32_t longitude = read32(cursor + 2), latitude = read32(cursor + 6);
    cursor += 10;
    if (count < 2 || count > 96 || longitude < -540000 || longitude > 540000
        || latitude < -90000 || latitude > 90000) return false;
    float ax = 0.0f, ay = 0.0f;
    bool previous = project(p, latitude * 0.001f, longitude * 0.001f, ax, ay);
    for (unsigned point = 1; point < count; ++point) {
      int32_t dx, dy;
      if (!readDelta(cursor, end, dx) || !readDelta(cursor, end, dy)
          || dx < -360000 || dx > 360000 || dy < -180000 || dy > 180000) return false;
      // Bounds checked in 64 bits before updating decoded coordinates.
      const int64_t next_lon = int64_t(longitude) + dx, next_lat = int64_t(latitude) + dy;
      if (next_lon < -540000 || next_lon > 540000 || next_lat < -90000 || next_lat > 90000) return false;
      longitude = int32_t(next_lon);
      latitude = int32_t(next_lat);
      float bx = 0.0f, by = 0.0f;
      const bool current = project(p, latitude * 0.001f, longitude * 0.001f, bx, by);
      if (previous && current) drawSegment(p, ax, ay, bx, by, line, context);
      previous = current;
      ax = bx;
      ay = by;
    }
  }
  return true;
}

} // namespace

bool projectWorldPoint(const MapView& view, double latitude, double longitude, int& x, int& y) {
  Projection p;
  float px, py;
  if (longitude < -180.0 || longitude > 180.0 || !makeProjection(view, p) || !project(p, latitude, longitude, px, py)
      || px < -0.5f || py < -0.5f || px >= p.width - 0.5f || py >= p.height - 0.5f) return false;
  x = int(lroundf(px));
  y = int(lroundf(py));
  return true;
}

bool renderWorldMap(const MapView& view, MapLine line, void* context) {
  Projection p;
  if (!line || !makeProjection(view, p)) return false;
  uint8_t scratch[data::kScratchBytes];
  for (const auto& chunk : data::kChunks) {
    if (!visibleChunk(p, chunk)) continue;
    if (chunk.raw > sizeof(scratch) || chunk.offset > sizeof(data::kDeflate)
        || chunk.packed > sizeof(data::kDeflate) - chunk.offset) return false;
    unsigned int size = chunk.raw;
    if (tinf_uncompress_exact(scratch, &size, data::kDeflate + chunk.offset, chunk.packed) != TINF_OK
        || size != chunk.raw || !drawChunk(p, scratch, size, line, context)) return false;
  }
  return true;
}

#if defined(POCKET_WORLD_MAP_TEST)
bool renderWorldMapChunkForTest(const MapView& view, const uint8_t* bytes, size_t size,
                               MapLine line, void* context) {
  Projection p;
  return bytes && line && makeProjection(view, p) && drawChunk(p, bytes, size, line, context);
}
#endif

}}}
#endif
