# MeshPocket worldwide outline

`PocketWorldMapData.generated.h` contains an outline of the world's land,
including all 1,422 rings from Natural Earth's **1:50m land, version 4.1.0**.
It has no roads, rivers, borders, labels or ocean raster. Small source islands
are retained; this is not a navigational chart. Around 100–200 km of vertical
map extent the coarse outline is useful. Closer zooms show node positions
against the same coarse background, not more geographic detail.

Source: <https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-land/>
Archive: <https://naturalearth.s3.amazonaws.com/50m_physical/ne_50m_land.zip>
SHA-256: `0b8e670cf80dce9cbebe2a193bc44ba5602758c22e1fa603980553646d7ff162`

Natural Earth data is public domain:
<https://www.naturalearthdata.com/about/terms-of-use/>.
No OpenStreetMap map assets or region-specific assets are used.

Generate with Python and the pinned `requirements-build.txt` dependencies:

```
python tools/meshpocket_map/pack_world_map.py --source-zip ne_50m_land.zip
python tools/meshpocket_map/pack_world_map.py --source-zip ne_50m_land.zip --check
```

Without `--source-zip`, the generator downloads that archive and verifies its
digest before reading it. The checked-in generated header makes normal
firmware builds independent of network access and GIS tools.

The deterministic generator uses kilometre-scaled Ramer–Douglas–Peucker
simplification with a 4 km tolerance, then rounds coordinates to 0.001 degrees.
Its local metric is an approximation, especially on large polar polygons;
the 4 km setting is not a guaranteed geodesic error bound. Islands that would
collapse are kept as at least three distinct vertices. Adjacent fragments
share an endpoint, so splitting never removes a connecting edge. Spatially
sorted fragments use signed delta varints and independent raw DEFLATE chunks,
compressed on the host with Google Zopfli **0.4.3, 1,000 iterations**. There is
no compression work on the device. Each indexed chunk has geographic bounds,
so local views skip unrelated data.

The pack uses **79,890 compressed bytes + 768 bytes of index**. Rendering uses
one temporary **3,072-byte** decode buffer and the existing bounded `tinf`
decoder. No map heap allocation, persistent geometry cache, land fill edge
table, or framebuffer is allocated. Lines are clipped to the caller's
viewport using a local azimuthal equidistant projection, which wraps the
antimeridian and supports views centred on either pole. Coastlines and node
markers use the same projection. Its internal geometry uses the nRF52840's
single-precision FPU. The 20,000 km setting switches to a full-world
equirectangular overview, centred on the selected longitude and the equator.
Seam crossings are split at the map edges, not joined across the middle.
