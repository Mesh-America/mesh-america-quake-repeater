#!/usr/bin/env python3
"""Measure exact-text decoding of plausible manual Morse timing variations."""
from pathlib import Path
import unittest
from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]


class HumanMorseTimingTests(unittest.TestCase):
    def test_actual_hil_sender_scheduler_decodes_human_variations_exactly(self):
        code = (ROOT / "test/fixtures/morse_rx_hil_human.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_HIL=1", "-DMESH_MORSE_MAX_WPM=240",
                                               "-DMESH_MORSE_HIL_FAST_OFF_DEBOUNCE=1"))
        rows = [line.split("\t") for line in output.splitlines()]
        self.assertEqual(len(rows), 154)
        for row in rows:
            with self.subTest(wpm=row[0], sample_ms=row[1], timing=row[2]):
                self.assertEqual(row[3], "PASS")
                self.assertEqual(row[4], "CQ DE TEST 73 SOS ")

    def actual_rows(self):
        code = (ROOT / "test/fixtures/morse_rx_human.cpp").read_text(encoding="ascii")
        output = compile_run(self, code)
        rows = [line.split("\t") for line in output.splitlines()]
        self.assertEqual(len(rows), 98)
        return rows

    def test_actual_decoder_supported_human_timing_is_exact_without_normalization(self):
        rows = [row for row in self.actual_rows() if row[2] != "farnsworth_2_0"]
        self.assertEqual(len(rows), 84)
        failures = [row for row in rows if row[4] != "PASS" or row[5] != "CQ DE TEST 73 SOS "]
        self.assertEqual(failures, [], "Strict human timing matrix failures:\n" +
                         "\n".join("\t".join(row) for row in failures))

    def test_doubled_character_spacing_is_explicitly_unsupported_not_a_feature_pass(self):
        # Without an explicit spacing hint, six dot units can denote either
        # a stretched letter gap or a short word gap. Characterize that known
        # ambiguity honestly; never count its spaced output as an exact decode.
        rows = [row for row in self.actual_rows() if row[2] == "farnsworth_2_0"]
        self.assertEqual(len(rows), 14)
        for row in rows:
            with self.subTest(wpm=row[0], sample_ms=row[1]):
                self.assertEqual(row[4], "FAIL")
                self.assertEqual(row[5], "C Q D E T E S T 7 3 S O S ")
                self.assertNotEqual(row[5], "CQ DE TEST 73 SOS ")


if __name__ == "__main__":
    unittest.main()
