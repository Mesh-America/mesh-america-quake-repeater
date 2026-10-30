#!/usr/bin/env python3
"""Build the coarse, worldwide Pocket coastline from pinned Natural Earth land."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from zopfli_compress import MAXIMUM_ITERATIONS, ZOPFLI_VERSION, raw_deflate_compress

URL = "https://naturalearth.s3.amazonaws.com/50m_physical/ne_50m_land.zip"
SOURCE_SHA256 = "0b8e670cf80dce9cbebe2a193bc44ba5602758c22e1fa603980553646d7ff162"
OUTPUT = ROOT / "src/helpers/ui/PocketWorldMapData.generated.h"
SCALE = 1000
TOLERANCE_KM = 4.0
BLOCK_BYTES = 3072
FRAGMENT_POINTS = 96


def source_rings(archive: bytes):
    if hashlib.sha256(archive).hexdigest() != SOURCE_SHA256:
        raise ValueError("Natural Earth source SHA-256 mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        if source.read("ne_50m_land.VERSION.txt").strip() != b"4.1.0":
            raise ValueError("unexpected Natural Earth release")
        data = source.read("ne_50m_land.shp")
    if len(data) < 100 or struct.unpack_from(">I", data)[0] != 9994:
        raise ValueError("invalid shapefile header")
    offset = 100
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated shapefile record")
        length = struct.unpack_from(">I", data, offset + 4)[0] * 2
        offset += 8
        record = data[offset:offset + length]
        offset += length
        if len(record) != length or length < 44:
            raise ValueError("truncated polygon")
        kind, = struct.unpack_from("<I", record)
        if kind != 5:
            raise ValueError("expected 2D polygon")
        parts, points = struct.unpack_from("<II", record, 36)
        if not parts or not points or 44 + parts * 4 + points * 16 != length:
            raise ValueError("invalid polygon dimensions")
        starts = struct.unpack_from(f"<{parts}I", record, 44) + (points,)
        coords = [struct.unpack_from("<dd", record, 44 + parts * 4 + i * 16)
                  for i in range(points)]
        for start, stop in zip(starts, starts[1:]):
            ring = coords[start:stop]
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("invalid closed land ring")
            yield ring


def rdp(points, tolerance):
    """Iterative RDP in kilometres; no dependency on GIS library versions."""
    kept = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        furthest, distance2 = first, tolerance * tolerance
        for i in range(first + 1, last):
            px, py = points[i]
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2)) if length2 else 0
            candidate = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if candidate > distance2:
                furthest, distance2 = i, candidate
        if furthest != first:
            kept.add(furthest)
            stack.extend(((first, furthest), (furthest, last)))
    return sorted(kept)


def simplify(ring):
    # Unwrap before simplification so a dateline crossing is a short edge.
    unwrapped = [ring[0]]
    for longitude, latitude in ring[1:]:
        previous = unwrapped[-1][0]
        longitude += 360 * math.floor((previous - longitude + 180) / 360)
        unwrapped.append((longitude, latitude))
    mean_latitude = sum(p[1] for p in unwrapped) / len(unwrapped)
    cosine = max(0.01, math.cos(math.radians(mean_latitude)))
    metric = [(x * 111.195 * cosine, y * 111.195) for x, y in unwrapped]
    selected = rdp(metric, TOLERANCE_KM)
    # Keep small islands as a triangle rather than dropping the entire ring.
    if len(selected) < 4:
        ax, ay = metric[0]
        opposite = max(range(1, len(metric) - 1),
                       key=lambda i: (metric[i][0] - ax) ** 2 + (metric[i][1] - ay) ** 2)
        bx, by = metric[opposite]
        third = max(range(1, len(metric) - 1),
                    key=lambda i: abs((bx - ax) * (metric[i][1] - ay) - (by - ay) * (metric[i][0] - ax)))
        selected = sorted({0, opposite, third, len(metric) - 1})
    quantized = []
    for i in selected:
        x, y = unwrapped[i]
        point = (round(x * SCALE), round(y * SCALE))
        if not quantized or point != quantized[-1]:
            quantized.append(point)
    if len(set(quantized)) < 3 or quantized[0] != quantized[-1]:
        raise ValueError("quantization collapsed a land ring")
    return quantized


def varint(value):
    value = (value << 1) if value >= 0 else ((-value << 1) - 1)
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return result


def fragment_bytes(fragment):
    result = bytearray(struct.pack("<Hii", len(fragment), *fragment[0]))
    for (ax, ay), (bx, by) in zip(fragment, fragment[1:]):
        result.extend(varint(bx - ax))
        result.extend(varint(by - ay))
    return bytes(result)


def pack(archive, compressor=raw_deflate_compress):
    rings = [simplify(ring) for ring in source_rings(archive)]
    fragments = []
    for ring in rings:
        for start in range(0, len(ring) - 1, FRAGMENT_POINTS - 1):
            points = ring[start:start + FRAGMENT_POINTS]
            xs, ys = zip(*points)
            bounds = (min(xs), min(ys), max(xs), max(ys))
            longitude = ((bounds[0] + bounds[2]) // 2 + 180000) % 360000 - 180000
            latitude = (bounds[1] + bounds[3]) // 2
            fragments.append(((longitude // 10000, latitude // 10000), bounds, fragment_bytes(points)))
    fragments.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    raw_blocks, bounds, current = [], [], bytearray()
    current_bounds = None
    for _, box, encoded in fragments:
        if len(current) + len(encoded) > BLOCK_BYTES:
            raw_blocks.append(bytes(current))
            bounds.append(current_bounds)
            current, current_bounds = bytearray(), None
        current.extend(encoded)
        current_bounds = box if current_bounds is None else (
            min(current_bounds[0], box[0]), min(current_bounds[1], box[1]),
            max(current_bounds[2], box[2]), max(current_bounds[3], box[3]))
    if current:
        raw_blocks.append(bytes(current))
        bounds.append(current_bounds)
    packed, descriptors = bytearray(), []
    for raw, box in zip(raw_blocks, bounds):
        compressed = compressor(raw, numiterations=MAXIMUM_ITERATIONS)
        if zlib.decompress(compressed, wbits=-15) != raw:
            raise ValueError("DEFLATE round-trip failed")
        descriptors.append((len(packed), len(compressed), len(raw), *box))
        packed.extend(compressed)
    return bytes(packed), descriptors, {"rings": len(rings), "points": sum(len(ring) for ring in rings),
                                      "raw_bytes": sum(map(len, raw_blocks)), "chunks": len(raw_blocks)}


def render(archive):
    packed, blocks, stats = pack(archive)
    # uint32_t offset, uint16_t packed/raw lengths, four int32_t bounds.
    stats.update(packed_bytes=len(packed), index_bytes=len(blocks) * 24,
                 firmware_data_bytes=len(packed) + len(blocks) * 24)
    lines = ["// Generated by tools/meshpocket_map/pack_world_map.py; do not edit.",
             "// Natural Earth 1:50m land 4.1.0, public domain; see tools/meshpocket_map/README.md.",
             f"// Source SHA-256: {SOURCE_SHA256}",
             f"// Zopfli {ZOPFLI_VERSION}, {MAXIMUM_ITERATIONS} iterations; 4 km RDP, 0.001 degree coordinates.",
             "#pragma once", "#include <stdint.h>", "namespace mesh { namespace ui { namespace pocket { namespace data {",
             "struct Chunk { uint32_t offset; uint16_t packed, raw; int32_t west, south, east, north; };",
             f"static constexpr unsigned kScratchBytes = {BLOCK_BYTES};",
             f"static constexpr unsigned kRingCount = {stats['rings']};",
             "static const Chunk kChunks[] = {"]
    lines.extend("  {%d, %d, %d, %d, %d, %d, %d}," % block for block in blocks)
    lines.extend(("};", "static const uint8_t kDeflate[] = {"))
    for offset in range(0, len(packed), 24):
        lines.append("  " + ",".join(f"0x{byte:02x}" for byte in packed[offset:offset + 24]) + ",")
    lines.extend(("};", "}}}}", ""))
    return "\n".join(lines), stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, help="already downloaded pinned Natural Earth archive")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    archive = args.source_zip.read_bytes() if args.source_zip else urllib.request.urlopen(URL, timeout=60).read()
    header, stats = render(archive)
    if args.check:
        if args.output.read_text(encoding="utf-8") != header:
            raise SystemExit("generated worldwide map is stale")
    else:
        args.output.write_text(header, encoding="utf-8", newline="\n")
    print(json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
