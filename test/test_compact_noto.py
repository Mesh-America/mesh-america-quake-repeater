"""Production Noto compression preserves all selected font pixels and metrics."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_compact_noto as generate
import generate_compact_arial as codec


HEADER = ROOT / "src/helpers/ui/CompactNotoFonts.h"
HARNESS = ROOT / "test/fixtures/compact_noto/test.cpp"


class CompactNotoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts, cls.license = generate.read_fonts()
        cls.header = HEADER.read_text(encoding="utf-8")

    def compile_and_run(self, header=None, invalid=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            if header is not None:
                include = folder / "helpers/ui"
                include.mkdir(parents=True)
                (include / "CompactNotoFonts.h").write_text(header, encoding="utf-8")
                (folder / "helpers/ota/tinf").mkdir(parents=True)
                (folder / "helpers/ota/tinf/tinf.h").write_text(
                    (ROOT / "src/helpers/ota/tinf/tinf.h").read_text(encoding="utf-8"), encoding="utf-8")
            decoder = folder / "tinf.o"
            subprocess.run([
                "cc", "-Os", "-DMESHCORE_TINF_IMPLEMENTATION=1", "-c",
                str(ROOT / "src/helpers/ota/tinf/tinflate.c"), "-o", str(decoder),
            ], check=True)
            executable = folder / "fonts"
            subprocess.run([
                "c++", "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror",
                f"-I{folder}", f"-I{ROOT / 'src'}", str(HARNESS),
                str(HARNESS.with_name("other.cpp")), str(decoder), "-o", str(executable),
            ], check=True)
            return subprocess.run(
                [str(executable)] + (["invalid"] if invalid else []),
                text=True, capture_output=True, check=True).stdout.splitlines()

    def test_generated_header_matches_authoritative_mode7_and_has_required_notice(self):
        self.assertEqual(self.header, generate.generate_header(self.fonts, self.license))
        self.assertEqual([len(font.original) for font in self.fonts], [4419, 8176])
        self.assertNotIn("FONT_0", self.header)
        self.assertNotIn("MESH_ARIAL_EXPERIMENT", self.header)
        self.assertNotIn("decodeRle", self.header)
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", self.header)
        self.assertIn("Copyright 2015 Google Inc. All Rights Reserved.", self.header)
        self.assertIn("4efc2789b9fcaa87b6b55f19c25ac9a2919e4f9ca31d6b5b97bea7977d729d4f", self.header)
        self.assertIn("Pillow 12.3.0 / FreeType 2.14.3", self.header)

    def test_all_glyph_chunks_roundtrip_in_at_most_512_decoded_bytes(self):
        total = 0
        for font in self.fonts:
            packed, rows, offsets, lengths = codec.chunk_font(font)
            raw = [zlib.decompress(packed[offsets[group]:offsets[group + 1]], -15)
                   for group in range(len(lengths))]
            self.assertEqual(list(map(len, raw)), list(lengths))
            self.assertLessEqual(max(lengths), 512)
            self.assertEqual(len(rows), 224)
            self.assertEqual(sum(bool(glyph.bitmap) for glyph in font.glyphs), 189)
            for glyph, (location, length, width) in zip(font.glyphs, rows):
                self.assertEqual((length, width), (len(glyph.bitmap), glyph.width))
                if length:
                    self.assertEqual(raw[location >> 9][(location & 511):(location & 511) + length], glyph.bitmap)
                else:
                    self.assertEqual(location, 0xffff)
            total += len(packed) + len(codec.descriptor(font, rows)) + 2 * (len(offsets) + len(lengths))
        self.assertEqual(total, 6777)

    def test_google_zopfli_requires_1000_iterations(self):
        from unittest.mock import patch
        codec.chunk_font.cache_clear()
        original = codec.raw_deflate_compress
        with patch.object(codec, "raw_deflate_compress", wraps=original) as compressor:
            generate.generate_header(self.fonts, self.license)
        self.assertEqual(compressor.call_count, 22)
        self.assertTrue(all(call.kwargs == {"numiterations": 1000} for call in compressor.call_args_list))

    def test_cpp_all448_glyphs_match_raw_mode7_without_experimental_macro(self):
        expected = []
        for id, font in enumerate(self.fonts, 1):
            expected.append("F " + " ".join(map(str, (id, *font.header))))
            for slot, glyph in enumerate(font.glyphs):
                expected.append(f"G {id} {slot + font.header[2]} {glyph.width} {len(glyph.bitmap)} {glyph.bitmap.hex()}")
        self.assertEqual(self.compile_and_run(), expected)

    def test_cpp_rejects_corrupt_descriptor_deflate_truncation_and_trailing_bytes(self):
        invalid_headers = [re.sub(
            r"(static const uint8_t FONT_1_DESCRIPTOR\[\] = \{\s*"
            r"(?:0x[0-9a-f]{2},\s*){8})0x[0-9a-f]{2},\s*0x[0-9a-f]{2}",
            lambda match: match[1] + "0xff, 0xfe", self.header)]
        invalid_headers.append(re.sub(
            r"(static const uint8_t FONT_1_DATA\[\] = \{\s*)0x[0-9a-f]{2}",
            lambda match: match[1] + "0x07", self.header))
        offsets = re.search(r"static const uint16_t FONT_1_OFFSETS\[\] = \{\s*0, (\d+)", self.header)
        for end in (1, int(offsets[1]) + 1):
            invalid_headers.append(re.sub(
                r"(static const uint16_t FONT_1_OFFSETS\[\] = \{\s*0, )\d+",
                lambda match: match[1] + str(end), self.header))
        for header in invalid_headers:
            self.assertNotEqual(header, self.header)
            self.compile_and_run(header, invalid=True)

    def test_reader_rejects_missing_source_coverage_or_license(self):
        source = generate.SOURCE.read_text(encoding="utf-8")
        invalid = [source.replace("#if MESH_ARIAL_EXPERIMENT == 7", "#if MESH_ARIAL_EXPERIMENT == 17"),
                   source.replace("SIL OPEN FONT LICENSE Version 1.1", "removed license")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.h"
            for content in invalid:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    generate.read_fonts(path)


if __name__ == "__main__":
    unittest.main()
