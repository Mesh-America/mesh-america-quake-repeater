"""Generate optional sans-serif family trials at the existing Arial ink sizes.

This is not part of normal firmware builds: checked-in bitmap arrays need no
Pillow or TrueType fonts on the build host. Regeneration requires Pillow 12.3.0
with FreeType 2.14.3 and the SHA-pinned upstream font files below. The derived
font names are MeshFontTrial4..8, not their sources' reserved font names.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import struct

from generate_compact_arial import Font, Glyph, ROOT, array, chunk_font, read_fonts, whole_font


OUTPUT = ROOT / "src/helpers/ui/FontFamilyTrials.h"
PILLOW_VERSION = "12.3.0"
FREETYPE_VERSION = "2.14.3"


@dataclass(frozen=True)
class Family:
    mode: int
    source: str
    filename: str
    sha256: str
    sizes: tuple[int, int]
    spdx: str
    upstream: str


FAMILIES = (
    Family(4, "Liberation Sans", "LiberationSans-Regular.ttf",
           "597589a852868f782c68e25112bab7785b34bc726f6160dca1519198c6e8c762",
           (16, 24), "OFL-1.1", "https://github.com/liberationfonts/liberation-fonts"),
    Family(5, "Noto Sans", "NotoSans-Regular.ttf",
           "6b04c8dd65af6b73eb4279472ed1580b29102d6496a377340e80a40cdb3b22c9",
           (16, 24), "OFL-1.1", "https://github.com/notofonts/noto-fonts"),
    Family(6, "DejaVu Sans", "DejaVuSans.ttf",
           "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
           (16, 23), "Bitstream-Vera AND LicenseRef-Arev", "https://github.com/dejavu-fonts/dejavu-fonts"),
    Family(7, "Noto Sans Condensed", "NotoSans-Condensed.ttf",
           "4efc2789b9fcaa87b6b55f19c25ac9a2919e4f9ca31d6b5b97bea7977d729d4f",
           (16, 24), "OFL-1.1", "https://github.com/notofonts/noto-fonts"),
    Family(8, "DejaVu Sans Condensed", "DejaVuSansCondensed.ttf",
           "8550cd5ca1acb65a8fc7877c46939cd0b4d909f8e7bc1e24716873d918c5e549",
           (16, 23), "Bitstream-Vera AND LicenseRef-Arev", "https://github.com/dejavu-fonts/dejavu-fonts"),
)


def sfnt_tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    count = struct.unpack_from(">H", data, 4)[0]
    result = {}
    for index in range(count):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        if offset + length > len(data):
            raise ValueError("Truncated TrueType table")
        result[tag] = offset, length
    return result


def name_records(data: bytes) -> dict[int, str]:
    offset, _length = sfnt_tables(data)[b"name"]
    _format, count, strings = struct.unpack_from(">HHH", data, offset)
    records = {}
    for index in range(count):
        platform, _encoding, _language, name, length, relative = struct.unpack_from(
            ">HHHHHH", data, offset + 6 + 12 * index)
        raw = data[offset + strings + relative:offset + strings + relative + length]
        if platform in (0, 3):
            records[name] = raw.decode("utf-16-be")
        elif platform == 1 and name not in records:
            records[name] = raw.decode("mac_roman")
    return records


def unicode_coverage(data: bytes) -> set[int]:
    """Read supported cmap4/cmap12 codepoints; never silently use .notdef."""
    offset, _length = sfnt_tables(data)[b"cmap"]
    _version, count = struct.unpack_from(">HH", data, offset)
    coverage = set()
    for index in range(count):
        platform, encoding, relative = struct.unpack_from(">HHI", data, offset + 4 + 8 * index)
        if platform != 0 and not (platform == 3 and encoding in (1, 10)):
            continue
        table = offset + relative
        format = struct.unpack_from(">H", data, table)[0]
        if format == 12:
            groups = struct.unpack_from(">I", data, table + 12)[0]
            for group in range(groups):
                start, end, first = struct.unpack_from(">III", data, table + 16 + 12 * group)
                coverage.update(code for code in range(start, min(end, 255) + 1) if first + code - start)
        elif format == 4:
            segments = struct.unpack_from(">H", data, table + 6)[0] // 2
            end_base = table + 14
            start_base = end_base + 2 * segments + 2
            delta_base = start_base + 2 * segments
            range_base = delta_base + 2 * segments
            for segment in range(segments):
                start = struct.unpack_from(">H", data, start_base + 2 * segment)[0]
                end = struct.unpack_from(">H", data, end_base + 2 * segment)[0]
                delta = struct.unpack_from(">H", data, delta_base + 2 * segment)[0]
                relative_glyph = struct.unpack_from(">H", data, range_base + 2 * segment)[0]
                for code in range(start, min(end, 255) + 1):
                    if relative_glyph:
                        glyph_offset = range_base + 2 * segment + relative_glyph + 2 * (code - start)
                        glyph = struct.unpack_from(">H", data, glyph_offset)[0]
                        glyph = ((glyph + delta) & 0xffff) if glyph else 0
                    else:
                        glyph = (code + delta) & 0xffff
                    if glyph:
                        coverage.add(code)
    return coverage


def make_font(name: str, header: bytes, glyphs: list[Glyph]) -> Font:
    table = bytearray(header)
    bitmap = bytearray()
    for glyph in glyphs:
        if len(glyph.bitmap) > 255 or glyph.width > 255:
            raise ValueError("Rasterized glyph exceeds ThingPulse byte metadata")
        table.extend((len(bitmap) if glyph.bitmap else 0xffff).to_bytes(2, "big"))
        table.extend((len(glyph.bitmap), glyph.width))
        bitmap.extend(glyph.bitmap)
    return Font(name, bytes(table + bitmap), tuple(glyphs))


def rasterize(family: Family, source: Path, baseline_fonts: tuple[Font, ...]):
    from PIL import Image, ImageDraw, ImageFont, features
    if Image.__version__ != PILLOW_VERSION or features.version("freetype2") != FREETYPE_VERSION:
        raise RuntimeError(f"Require Pillow{PILLOW_VERSION}/FreeType{FREETYPE_VERSION} for deterministic font trials")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != family.sha256:
        raise ValueError(f"{source.name}: source font hash differs from the pinned trial")
    names = name_records(data)
    coverage = unicode_coverage(data)
    fonts = []
    metrics = []
    for id, pixel_size in enumerate(family.sizes, 1):
        base = baseline_fonts[id]
        baseline = 15 if id == 1 else 22
        font = ImageFont.truetype(str(source), pixel_size, layout_engine=ImageFont.Layout.BASIC)
        glyphs = []
        shifted_x, shifted_y = [], []
        for slot, original in enumerate(base.glyphs):
            code = base.header[2] + slot
            character = chr(code)
            advance = int(math.floor(font.getlength(character) + 0.5)) if code in coverage else original.width
            if not original.bitmap:
                # Control slots stay blank, not .notdef boxes. Spaces use the
                # candidate font's own spacing; other blanks retain zero width.
                glyphs.append(Glyph(advance if code in (32, 160) else original.width, b""))
                continue
            if code not in coverage:
                raise ValueError(f"{family.source}: U+{code:04X} missing from Unicode cmap")
            image = Image.new("L", (128, 128), 0)
            ImageDraw.Draw(image).text((48, 48), character, font=font, fill=255, anchor="ls")
            image = image.point(lambda value: 255 if value >= 128 else 0)
            bbox = image.getbbox()
            if bbox is None:
                raise ValueError(f"{family.source}: drawable U+{code:04X} rasterized blank")
            left, top, right, bottom = (value - 48 for value in bbox)
            if bottom - top > base.header[1]:
                raise ValueError(f"{family.source}: U+{code:04X} is too tall for the unchanged line box")
            x_shift = max(0, -left)
            y_shift = max(0, -(baseline + top))
            y_shift -= max(0, baseline + bottom + y_shift - base.header[1])
            width = max(advance + x_shift, right + x_shift)
            if baseline + top + y_shift < 0 or baseline + bottom + y_shift > base.header[1]:
                raise ValueError("Glyph placement would clip pixels")
            if x_shift:
                shifted_x.append(code)
            if y_shift:
                shifted_y.append((code, y_shift))
            raster_height = (base.header[1] + 7) // 8
            bitmap = bytearray(width * raster_height)
            for y in range(bbox[1], bbox[3]):
                for x in range(bbox[0], bbox[2]):
                    if image.getpixel((x, y)):
                        dest_x = x - 48 + x_shift
                        dest_y = y - 48 + baseline + y_shift
                        bitmap[dest_x * raster_height + dest_y // 8] |= 1 << (dest_y & 7)
            while bitmap and not bitmap[-1]:
                bitmap.pop()
            glyphs.append(Glyph(width, bytes(bitmap)))
        made = make_font(f"MeshFontTrial{family.mode}_{16 if id == 1 else 24}", base.header, glyphs)
        top, bottom = ink_y_bounds(made, ord("H"))
        if (top, bottom) != ((3, 14) if id == 1 else (5, 21)):
            raise ValueError("The H baseline/top differs from the original Arial placement")
        fonts.append(made)
        metrics.append({"nominal": pixel_size, "cap": bottom - top + 1, "H_top": top,
                        "baseline": baseline, "line_box": base.header[1],
                        "bearing_shifts": shifted_x, "vertical_shifts": shifted_y})
    return tuple(fonts), metrics, names


def ink_y_bounds(font: Font, code: int) -> tuple[int, int]:
    glyph = font.glyphs[code - font.header[2]]
    stride = (font.header[1] + 7) // 8
    rows = [8 * (index % stride) + bit for index, value in enumerate(glyph.bitmap)
            for bit in range(8) if value & (1 << bit)]
    return min(rows), max(rows)


def license_notice(family: Family, names: dict[int, str]) -> str:
    if family.mode in (4, 5, 7):
        text = (ROOT / "tools/sensecap_indicator_font/OFL-1.1.txt").read_text(encoding="utf-8")
        text = text[text.index("SIL OPEN FONT LICENSE Version 1.1"):]
        notice = names[0] + "\n"
        if family.mode == 4:
            notice += "Reserved Font Names: Arimo, Tinos, Cousine, Liberation.\n"
        return notice + "\n" + text
    return names[0] + "\n\n" + names[13]


def generate_header(trials) -> str:
    output = ["// Generated by scripts/generate_font_family_trials.py; do not edit.\n"
              "// Opt-in derived fonts named MeshFontTrial4..8. Same visible cap sizes\n"
              "// (12/17 px) and line boxes (19/28 px) as Arial16/24; all 189 drawable\n"
              "// Latin-1 slots preserved. These are appearance trials, not defaults.\n"
              "// Rasterizer: Pillow 12.3.0, FreeType 2.14.3; grayscale threshold 128.\n"
              "#pragma once\n#include <stdint.h>\n"
              "#if MESH_ARIAL_EXPERIMENT < 4 || MESH_ARIAL_EXPERIMENT > 8\n"
              '#error "FontFamilyTrials.h is only for font experiment modes 4 through 8"\n#endif\n'
              "namespace mesh { namespace ui { namespace font_trials {"]
    for family, fonts, metrics, names in trials:
        output.append(f"#if MESH_ARIAL_EXPERIMENT == {family.mode}")
        comment = (f"Derived MeshFontTrial{family.mode}; source {family.source}, {names[5]}\n"
                   f"Source SHA256: {family.sha256}\nUpstream: {family.upstream}\n"
                   f"SPDX-License-Identifier: {family.spdx}\n"
                   "Full license/copyright follows; it applies to the bitmap font data.\n"
                   + license_notice(family, names))
        # Font metadata/license text may carry trailing spaces. Normalize only
        # whitespace, never the required copyright/license wording.
        comment = "\n".join(line.rstrip() for line in comment.splitlines())
        output.append("/*\n" + comment.replace("*/", "* /") + "\n*/")
        for id, (font, metric) in enumerate(zip(fonts, metrics), 1):
            output.append("// " + "; ".join(f"{key}={value}" for key, value in metric.items()))
            output.append(f"inline const uint8_t* fontStorage{id}() {{")
            output.append(array(f"TRIAL_{id}", font.original))
            output.append(f"return TRIAL_{id};\n}}")
        output.append("#endif")
    output.append("inline const uint8_t* font(unsigned id) {\n"
                  "  return id == 1 ? fontStorage1() : id == 2 ? fontStorage2() : nullptr;\n"
                  "}\n}}} // namespace mesh::ui::font_trials")
    return "\n\n".join(output) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=Path("C:/Windows/Fonts"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    baseline_fonts = read_fonts()
    trials = []
    for family in FAMILIES:
        fonts, metrics, names = rasterize(family, args.font_dir / family.filename, baseline_fonts)
        trials.append((family, fonts, metrics, names))
        if not args.check:
            print(f"mode {family.mode} {family.source}: raw={sum(len(font.original) for font in fonts)} "
                  f"whole-font Zopfli={sum(len(whole_font(font)) for font in fonts)}")
            for font, metric in zip(fonts, metrics):
                chunk, records, offsets, lengths = chunk_font(font)
                compressed_size = len(chunk) + 4 + 4 * len(records) + 2 * (len(offsets) + len(lengths))
                print(f"  {font.name}: raw={len(font.original)} chunked Zopfli={compressed_size} {metric}")
    header = generate_header(trials)
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != header:
            raise SystemExit("FontFamilyTrials.h is stale")
    else:
        OUTPUT.write_text(header, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
