"""Generate opt-in, lossless Arial font storage experiments.

The checked-in source font remains authoritative. Every one of its 224 slots,
including blank slots and their advance widths, survives these experiments.
Mode 2 uses per-glyph byte RLE; mode 3 independently inflates <=512-byte glyph
groups. Whole-font compression is measured only, not instantiated on the device.
Google Zopfli is used at 1,000 iterations; no compressor runs on the device.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from zopfli_compress import MAXIMUM_ITERATIONS, raw_deflate_compress


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/helpers/ui/OLEDDisplayFonts.cpp"
OUTPUT = ROOT / "src/helpers/ui/CompactArialFonts.h"
CHUNK_LIMIT = 512


@dataclass(frozen=True)
class Glyph:
    width: int
    bitmap: bytes


@dataclass(frozen=True)
class Font:
    name: str
    original: bytes
    glyphs: tuple[Glyph, ...]

    @property
    def header(self) -> bytes:
        return self.original[:4]


def read_fonts(path: Path = SOURCE) -> tuple[Font, ...]:
    source = path.read_text(encoding="utf-8")
    fonts = []
    for name, body in re.findall(
        r"const uint8_t (ArialMT_Plain_\d+)\[\] PROGMEM = \{(.*?)\};", source, re.S
    ):
        body = re.sub(r"//[^\n]*", "", body)
        data = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]+)", body))
        if len(data) < 4:
            raise ValueError(f"{name}: incomplete header")
        base = 4 + 4 * data[3]
        if base > len(data) or data[2] + data[3] > 256:
            raise ValueError(f"{name}: invalid character table")
        glyphs = []
        consumed = 0
        for index in range(data[3]):
            entry = data[4 + 4 * index:8 + 4 * index]
            offset = int.from_bytes(entry[:2], "big")
            length, width = entry[2:]
            if offset == 0xffff:
                if length:
                    raise ValueError(f"{name}: blank slot contains bitmap bytes")
                bitmap = b""
            else:
                if not length or offset != consumed or base + offset + length > len(data):
                    raise ValueError(f"{name}: invalid or non-contiguous bitmap")
                bitmap = data[base + offset:base + offset + length]
                consumed += length
            glyphs.append(Glyph(width, bitmap))
        if base + consumed != len(data):
            raise ValueError(f"{name}: trailing bitmap bytes")
        fonts.append(Font(name, data, tuple(glyphs)))
    if [font.name for font in fonts] != [f"ArialMT_Plain_{size}" for size in (10, 16, 24)]:
        raise ValueError("Expected the original Arial 10, 16 and 24 fonts")
    return tuple(fonts)


def rle_encode(data: bytes) -> bytes:
    """PackBits-style literals (1..128) and repeated bytes (3..130)."""
    output = bytearray()
    position = 0
    while position < len(data):
        run = 1
        while position + run < len(data) and data[position + run] == data[position] and run < 130:
            run += 1
        if run >= 3:
            output.extend((0x80 | (run - 3), data[position]))
            position += run
            continue
        first = position
        position += run
        while position < len(data) and position - first < 128:
            run = 1
            while position + run < len(data) and data[position + run] == data[position] and run < 3:
                run += 1
            if run >= 3:
                break
            position += min(run, 128 - (position - first))
        output.append(position - first - 1)
        output.extend(data[first:position])
    return bytes(output)


def rle_font(font: Font) -> tuple[bytes, tuple[tuple[int, int, int], ...]]:
    output = bytearray()
    records = []
    for glyph in font.glyphs:
        if not glyph.bitmap:
            records.append((0xffff, 0, glyph.width))
            continue
        compressed = rle_encode(glyph.bitmap)
        raw = len(compressed) >= len(glyph.bitmap)
        location = len(output) | (0x8000 if raw else 0)
        output.extend(glyph.bitmap if raw else compressed)
        records.append((location, len(glyph.bitmap), glyph.width))
    if len(output) >= 0x7fff:
        raise ValueError("RLE offsets no longer fit the 15-bit experiment format")
    return bytes(output), tuple(records)


@lru_cache(maxsize=None)
def chunk_font(font: Font) -> tuple[bytes, tuple[tuple[int, int, int], ...], tuple[int, ...], tuple[int, ...]]:
    chunks = []
    current = bytearray()
    records = []
    for glyph in font.glyphs:
        if not glyph.bitmap:
            records.append((0xffff, 0, glyph.width))
            continue
        if len(glyph.bitmap) > CHUNK_LIMIT:
            raise ValueError("A glyph exceeds the bounded font scratch buffer")
        if len(current) + len(glyph.bitmap) > CHUNK_LIMIT:
            chunks.append(bytes(current))
            current.clear()
        records.append(((len(chunks) << 9) | len(current), len(glyph.bitmap), glyph.width))
        current.extend(glyph.bitmap)
    if current:
        chunks.append(bytes(current))
    if len(chunks) >= 128:
        raise ValueError("Chunk identifiers exceed the packed 7-bit format")
    output = bytearray()
    offsets = [0]
    for chunk in chunks:
        output.extend(raw_deflate_compress(chunk, numiterations=MAXIMUM_ITERATIONS))
        offsets.append(len(output))
    if len(output) > 0xffff:
        raise ValueError("Compressed font offsets exceed 16 bits")
    return bytes(output), tuple(records), tuple(offsets), tuple(map(len, chunks))


@lru_cache(maxsize=None)
def whole_font(font: Font) -> bytes:
    return raw_deflate_compress(font.original, numiterations=MAXIMUM_ITERATIONS)


def array(name: str, data, ctype: str = "uint8_t", columns: int = 16) -> str:
    values = [f"0x{value:02x}" if ctype == "uint8_t" else str(value) for value in data]
    lines = [f"static const {ctype} {name}[] = {{"]
    for first in range(0, len(values), columns):
        lines.append("  " + ", ".join(values[first:first + columns]) + ",")
    lines.append("};")
    return "\n".join(lines)


def descriptor(font: Font, rows) -> bytes:
    output = bytearray(font.header)
    for location, length, width in rows:
        output.extend(location.to_bytes(2, "big"))
        output.extend((length, width))
    return bytes(output)


def generate_header(fonts: tuple[Font, ...]) -> str:
    output = [HEADER_START]
    for mode in (2, 3):
        output.append(f"#if MESH_ARIAL_EXPERIMENT == {mode}")
        for index, font in enumerate(fonts[1:], 1):
            prefix = f"FONT_{index}"
            # Inline function-local statics have one address across translation
            # units. Namespace-static arrays would silently break identify().
            output.append(f"inline const Font& fontStorage{index}() {{")
            if mode == 2:
                data, rows = rle_font(font)
                offsets, lengths = (), ()
            elif mode == 3:
                data, rows, offsets, lengths = chunk_font(font)
            output.append(array(prefix + "_DATA", data))
            output.append(array(prefix + "_DESCRIPTOR", descriptor(font, rows)))
            if offsets:
                output.append(array(prefix + "_OFFSETS", offsets, "uint16_t"))
                output.append(array(prefix + "_LENGTHS", lengths, "uint16_t"))
            output.append(
                f"static const Font {prefix} = {{ " + prefix + "_DESCRIPTOR, " + prefix + "_DATA, "
                + (prefix + "_OFFSETS, " + prefix + "_LENGTHS" if offsets else "nullptr, nullptr")
                + f", {len(lengths)}, {len(data)} }};"
            )
            output.append(f"return {prefix};\n}}")
        output.append("#endif")
    output.append(HEADER_END)
    return "\n\n".join(output) + "\n"


HEADER_START = r'''// Generated by scripts/generate_compact_arial.py; do not edit.
// Experiments are LOSSLESS: same Arial pixels, all 224 slots and advance widths.
// 2 = glyph RLE (<=91 scratch bytes); 3 = Zopfli 1000 chunks (<=512 scratch).
// Only Arial16 and Arial24 are instantiated; the unused initial Arial10 is not.
#pragma once
#include <stddef.h>
#include <stdint.h>
#if MESH_ARIAL_EXPERIMENT == 3
#include "../ota/tinf/tinf.h"
#endif
#if MESH_ARIAL_EXPERIMENT != 2 && MESH_ARIAL_EXPERIMENT != 3
#error "CompactArialFonts.h is an opt-in experiment for modes 2 and 3 only"
#endif
namespace mesh { namespace ui { namespace arial {
static constexpr size_t kScratchSize = MESH_ARIAL_EXPERIMENT == 2 ? 91 : 512;
struct Font {
  const uint8_t* descriptor;
  const uint8_t* data;
  const uint16_t* offsets;
  const uint16_t* rawLengths;
  uint16_t chunkCount;
  uint16_t dataLength;
};
struct Glyph {
  const uint8_t* data;
  uint8_t width;
  uint8_t length;
  bool drawable;
  bool valid;
};'''


HEADER_END = r'''inline const uint8_t* font(unsigned id) {
  return id == 1 ? fontStorage1().descriptor : id == 2 ? fontStorage2().descriptor : nullptr;
}
inline int identify(const uint8_t* descriptor) {
  return descriptor == fontStorage1().descriptor ? 1 : descriptor == fontStorage2().descriptor ? 2 : -1;
}
inline const Font* storage(const uint8_t* descriptor) {
  const int id = identify(descriptor);
  return id == 1 ? &fontStorage1() : id == 2 ? &fontStorage2() : nullptr;
}
// Writes only to caller scratch. No global cache, heap allocation, or mutable state.
inline bool decodeRle(const uint8_t* input, size_t inputLength,
                      uint8_t* output, size_t outputLength) {
  if ((!input && inputLength) || (!output && outputLength)) return false;
  size_t source = 0, dest = 0;
  while (source < inputLength) {
    const uint8_t token = input[source++];
    const size_t count = token < 128 ? size_t(token) + 1 : size_t(token & 127) + 3;
    if (count > outputLength - dest) return false;
    if (token < 128) {
      if (count > inputLength - source) return false;
      for (size_t j = 0; j < count; ++j) output[dest++] = input[source++];
    } else {
      if (source == inputLength) return false;
      const uint8_t value = input[source++];
      for (size_t j = 0; j < count; ++j) output[dest++] = value;
    }
  }
  return dest == outputLength;
}
inline Glyph glyph(const uint8_t* descriptor, uint8_t code, uint8_t* scratch, size_t capacity) {
  const Font* f = storage(descriptor);
  if (!f || code < descriptor[2] || unsigned(code - descriptor[2]) >= descriptor[3])
    return { nullptr, 0, 0, false, false };
  const unsigned slot = code - descriptor[2];
  const uint8_t* record = descriptor + 4 + 4 * slot;
  const unsigned location = (unsigned(record[0]) << 8) | record[1];
  const uint8_t length = record[2], width = record[3];
  if (!length) return { nullptr, width, 0, false, location == 0xffff };
#if MESH_ARIAL_EXPERIMENT == 2
  const unsigned first = location & 0x7fff;
  unsigned end = f->dataLength;
  for (unsigned next = slot + 1; next < descriptor[3]; ++next) {
    const uint8_t* nextRecord = descriptor + 4 + 4 * next;
    if (nextRecord[2]) { end = ((unsigned(nextRecord[0]) << 8) | nextRecord[1]) & 0x7fff; break; }
  }
  if (first > end || end > f->dataLength) return { nullptr, width, 0, false, false };
  if (location & 0x8000) {
    if (end - first != length) return { nullptr, width, 0, false, false };
    return { f->data + first, width, length, true, true };
  }
  if (!scratch || capacity < length || !decodeRle(f->data + first, end - first, scratch, length))
    return { nullptr, width, 0, false, false };
  return { scratch, width, length, true, true };
#elif MESH_ARIAL_EXPERIMENT == 3
  const unsigned group = location >> 9;
  const unsigned offset = location & 511;
  if (group >= f->chunkCount) return { nullptr, width, 0, false, false };
  const unsigned first = f->offsets[group], end = f->offsets[group + 1];
  const unsigned expected = f->rawLengths[group];
  if (!scratch || expected > kScratchSize || capacity < expected || offset + length > expected || first > end || end > f->dataLength)
    return { nullptr, width, 0, false, false };
  unsigned int produced = expected;
  if (tinf_uncompress_exact(scratch, &produced, f->data + first, end - first) != TINF_OK || produced != expected)
    return { nullptr, width, 0, false, false };
  return { scratch + offset, width, length, true, true };
#endif
}
}}} // namespace mesh::ui::arial'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the generated header without writing")
    args = parser.parse_args()
    fonts = read_fonts()
    header = generate_header(fonts)
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != header:
            raise SystemExit("CompactArialFonts.h is stale; regenerate the font experiments")
    else:
        OUTPUT.write_text(header, encoding="utf-8", newline="\n")
    print("font       original  RLE+table  chunks+table  wholefont  chunks")
    for font in fonts:
        rle, _ = rle_font(font)
        chunk, _, offsets, lengths = chunk_font(font)
        print(f"{font.name:20} {len(font.original):5}  {len(rle) + 4 * len(font.glyphs) + 4:9}  "
              f"{len(chunk) + 4 * len(font.glyphs) + 2 * (len(offsets) + len(lengths)) + 4:12}  "
              f"{len(whole_font(font)):9}  {len(lengths):6}")


if __name__ == "__main__":
    main()
