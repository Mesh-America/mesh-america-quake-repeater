"""Same-size libre font trials preserve the complete existing character coverage."""
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_font_family_trials as generate
from generate_compact_arial import Font, Glyph, read_fonts


HEADER = ROOT / "src/helpers/ui/FontFamilyTrials.h"


def parse_font(name, data):
    count = data[3]
    base = 4 + 4 * count
    glyphs = []
    consumed = 0
    for index in range(count):
        offset = int.from_bytes(data[4 + 4 * index:6 + 4 * index], "big")
        length, width = data[6 + 4 * index:8 + 4 * index]
        if offset == 0xffff:
            if length:
                raise ValueError("Blank glyph has bitmap bytes")
            bitmap = b""
        else:
            if not length or offset != consumed or base + offset + length > len(data):
                raise ValueError("Glyph data is not contiguous/in bounds")
            bitmap = data[base + offset:base + offset + length]
            consumed += length
        glyphs.append(Glyph(width, bitmap))
    if base + consumed != len(data):
        raise ValueError("Trailing font bytes")
    return Font(name, data, tuple(glyphs))


class FontFamilyTrialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = HEADER.read_text(encoding="utf-8")
        cls.baseline = read_fonts()
        cls.trials = {}
        for mode, body in re.findall(r"#if MESH_ARIAL_EXPERIMENT == ([45678])\s*(.*?)\n#endif", cls.text, re.S):
            fonts = []
            for id, encoded in re.findall(r"static const uint8_t TRIAL_([12])\[\] = \{(.*?)\};", body, re.S):
                data = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-f]{2})", encoded))
                fonts.append(parse_font(f"MeshFontTrial{mode}_{id}", data))
            cls.trials[int(mode)] = tuple(fonts)

    def test_all_five_trials_cover_exact_original_drawable_slots(self):
        self.assertEqual(set(self.trials), {4, 5, 6, 7, 8})
        for mode, fonts in self.trials.items():
            self.assertEqual(len(fonts), 2)
            for id, font in enumerate(fonts, 1):
                with self.subTest(mode=mode, id=id):
                    self.assertEqual(font.header, self.baseline[id].header)
                    self.assertEqual(len(font.glyphs), 224)
                    self.assertEqual([bool(glyph.bitmap) for glyph in font.glyphs],
                                     [bool(glyph.bitmap) for glyph in self.baseline[id].glyphs])
                    self.assertEqual(sum(bool(glyph.bitmap) for glyph in font.glyphs), 189)

    def test_H_visible_size_top_and_line_height_are_unchanged(self):
        for mode, fonts in self.trials.items():
            for id, font in enumerate(fonts, 1):
                with self.subTest(mode=mode, id=id):
                    self.assertEqual(generate.ink_y_bounds(font, ord("H")), (3, 14) if id == 1 else (5, 21))
                    self.assertEqual(font.header[1], 19 if id == 1 else 28)

    def test_every_glyph_pixel_fits_its_advance_and_line_box(self):
        for mode, fonts in self.trials.items():
            for id, font in enumerate(fonts, 1):
                stride = (font.header[1] + 7) // 8
                for code, glyph in enumerate(font.glyphs, 32):
                    with self.subTest(mode=mode, id=id, code=code):
                        self.assertLessEqual(len(glyph.bitmap), glyph.width * stride)
                        for index, value in enumerate(glyph.bitmap):
                            for bit in range(8):
                                if value & (1 << bit):
                                    self.assertLess(index // stride, glyph.width)
                                    self.assertLess((index % stride) * 8 + bit, font.header[1])

    def test_raw_byte_measurements_and_source_notices_are_exact(self):
        self.assertEqual({mode: sum(len(font.original) for font in fonts)
                          for mode, fonts in self.trials.items()},
                         {4: 14979, 5: 14871, 6: 15701, 7: 12595, 8: 14230})
        for family in generate.FAMILIES:
            self.assertIn(family.sha256, self.text)
            self.assertIn(family.upstream, self.text)
            self.assertIn(f"SPDX-License-Identifier: {family.spdx}", self.text)
        for notice in ("SIL OPEN FONT LICENSE Version 1.1", "Copyright (c) 2012 Red Hat, Inc.",
                       "Copyright 2015 Google Inc. All Rights Reserved.", "Bitstream Vera Fonts Copyright",
                       "Arev Fonts Copyright", "Copyright (c) 2006 by Tavmjong Bah."):
            self.assertIn(notice, self.text)
        self.assertNotIn("FONT_0", self.text)
        self.assertNotIn("LiberationSansNarrow", self.text)

    def test_serializer_preserves_glyph_bytes_and_missing_slot_width(self):
        base = self.baseline[1]
        self.assertEqual(generate.make_font(base.name, base.header, list(base.glyphs)), base)


if __name__ == "__main__":
    unittest.main()
