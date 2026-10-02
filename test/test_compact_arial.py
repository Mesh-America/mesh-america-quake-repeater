"""Lossless experimental Arial compression with the existing C tinf decoder."""
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_compact_arial as generate


HEADER = ROOT / "src/helpers/ui/CompactArialFonts.h"
HARNESS = ROOT / "test/fixtures/compact_arial/test.cpp"


def unpack_rle(data):
    output = bytearray()
    index = 0
    while index < len(data):
        token = data[index]
        index += 1
        if token < 128:
            count = token + 1
            output.extend(data[index:index + count])
            index += count
        else:
            output.extend(bytes((data[index],)) * ((token & 127) + 3))
            index += 1
    return bytes(output)


class CompactArialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = generate.read_fonts()
        cls.header = HEADER.read_text(encoding="utf-8")

    def compile_and_run(self, mode, header=None, invalid=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            if header is not None:
                include = folder / "helpers/ui"
                include.mkdir(parents=True)
                (include / "CompactArialFonts.h").write_text(header, encoding="utf-8")
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
                f"-DMESH_ARIAL_EXPERIMENT={mode}", f"-I{folder}", f"-I{ROOT / 'src'}",
                str(HARNESS), str(HARNESS.with_name("other.cpp")), str(decoder), "-o", str(executable),
            ], check=True)
            return subprocess.run(
                [str(executable)] + (["invalid"] if invalid else []),
                text=True, capture_output=True, check=True).stdout.splitlines()

    def test_generated_header_is_reproducible_and_omits_unused_10(self):
        self.assertEqual(self.header, generate.generate_header(self.fonts))
        self.assertNotIn("FONT_0", self.header)
        self.assertEqual([len(font.original) for font in self.fonts], [2731, 5049, 9643])
        self.assertEqual(max(len(glyph.bitmap) for font in self.fonts for glyph in font.glyphs), 91)

    def test_rle_and_raw_bypass_roundtrip_every_glyph_and_metric(self):
        for font in self.fonts:
            packed, rows = generate.rle_font(font)
            descriptor = generate.descriptor(font, rows)
            self.assertEqual(descriptor[:4], font.header)
            for index, (glyph, record) in enumerate(zip(font.glyphs, rows)):
                location, length, width = record
                self.assertEqual((length, width), (len(glyph.bitmap), glyph.width))
                self.assertEqual(descriptor[6 + 4 * index:8 + 4 * index], font.original[6 + 4 * index:8 + 4 * index])
                if not length:
                    self.assertEqual(location, 0xffff)
                    continue
                first = location & 0x7fff
                end = next((next_row[0] & 0x7fff for next_row in rows[index + 1:] if next_row[1]), len(packed))
                encoded = packed[first:end]
                self.assertEqual(encoded if location & 0x8000 else unpack_rle(encoded), glyph.bitmap)

    def test_rle_literal_and_run_boundaries(self):
        cases = [bytes(range(256)), b"x" * 130, b"x" * 131, b"x" * 260,
                 b"abc" + b"x" * 130 + b"def", b"", b"x", b"xx"]
        randomizer = random.Random(1234)
        cases += [bytes(randomizer.randrange(8) for _ in range(length)) for length in range(300)]
        for data in cases:
            self.assertEqual(unpack_rle(generate.rle_encode(data)), data)

    def test_zopfli_chunks_roundtrip_every_glyph_with_512_byte_cap(self):
        original_total = 0
        compressed_total = 0
        for font in self.fonts[1:]:
            packed, rows, offsets, lengths = generate.chunk_font(font)
            raw = [zlib.decompress(packed[offsets[index]:offsets[index + 1]], -15) for index in range(len(lengths))]
            self.assertEqual(list(map(len, raw)), list(lengths))
            self.assertLessEqual(max(lengths), 512)
            for glyph, (location, length, width) in zip(font.glyphs, rows):
                self.assertEqual((length, width), (len(glyph.bitmap), glyph.width))
                if length:
                    self.assertEqual(raw[location >> 9][(location & 511):(location & 511) + length], glyph.bitmap)
                else:
                    self.assertEqual(location, 0xffff)
            original_total += len(font.original)
            compressed_total += len(packed) + len(generate.descriptor(font, rows)) + 2 * (len(offsets) + len(lengths))
        self.assertEqual(original_total - compressed_total, 7555)

    def test_google_zopfli_uses_1000_iterations(self):
        from unittest.mock import patch
        generate.chunk_font.cache_clear()
        original = generate.raw_deflate_compress
        with patch.object(generate, "raw_deflate_compress", wraps=original) as compressor:
            generate.chunk_font(self.fonts[0])
        self.assertEqual(compressor.call_count, 4)
        self.assertTrue(all(call.kwargs == {"numiterations": 1000} for call in compressor.call_args_list))

    def test_cpp_both_variants_preserve_all_448_glyphs_and_metadata(self):
        expected = []
        for id, font in enumerate(self.fonts[1:], 1):
            expected.append("F " + " ".join(map(str, (id, *font.header))))
            for slot, glyph in enumerate(font.glyphs):
                expected.append(f"G {id} {slot + font.header[2]} {glyph.width} {len(glyph.bitmap)} {glyph.bitmap.hex()}")
        for mode in (2, 3):
            with self.subTest(mode=mode):
                self.assertEqual(self.compile_and_run(mode), expected)

    def test_cpp_corrupt_descriptor_or_deflate_stream_fails_closed(self):
        # Glyph 33 is the first bitmap; glyph32 is a blank space.
        for mode in (2, 3):
            bad = re.sub(
                r"(static const uint8_t FONT_1_DESCRIPTOR\[\] = \{\s*"
                r"(?:0x[0-9a-f]{2},\s*){8})0x[0-9a-f]{2},\s*0x[0-9a-f]{2}",
                lambda match: match[1] + "0xff, 0xfe", self.header)
            self.assertNotEqual(bad, self.header)
            self.compile_and_run(mode, bad, invalid=True)
        bad = re.sub(r"(static const uint8_t FONT_1_DATA\[\] = \{\s*)0x[0-9a-f]{2}",
                     lambda match: match[1] + "0x07", self.header)
        self.compile_and_run(3, bad, invalid=True)


if __name__ == "__main__":
    unittest.main()
