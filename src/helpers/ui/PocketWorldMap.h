#pragma once

#include <stddef.h>
#include <stdint.h>

namespace mesh { namespace ui { namespace pocket {

// Local azimuthal equidistant view. Height is the full vertical extent in km.
// At 20,000 km use a complete equirectangular world overview, centred at the
// requested longitude and the equator, with blank margins to preserve aspect.
// The coarse land outline is useful around 100-200 km; close zooms locate nodes.
struct MapView {
  double latitude, longitude, height_km;
  int width, height;
};

using MapLine = void (*)(void* context, int x0, int y0, int x1, int y1);

// Coordinates are relative to this viewport, including its clipped boundary.
// Returns false for an invalid view or corrupt built-in map data.
bool renderWorldMap(const MapView& view, MapLine line, void* context);
// Same projection as the coastline. False means invalid or outside the view.
bool projectWorldPoint(const MapView& view, double latitude, double longitude, int& x, int& y);

#if defined(POCKET_WORLD_MAP_TEST)
// Exercise the production bounded parser with malformed/truncated raw chunks.
bool renderWorldMapChunkForTest(const MapView& view, const uint8_t* bytes, size_t size,
                               MapLine line, void* context);
#endif

}}}
