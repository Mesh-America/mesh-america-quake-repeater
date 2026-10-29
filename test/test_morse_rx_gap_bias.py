"""Exercise actual RSSI decoding of shortened human gaps and RF OFF-edge bias."""
from pathlib import Path
import unittest

from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]


class MorseRxGapBiasTests(unittest.TestCase):
    def test_actual_sampled_decoder_retains_tight_letters_words_and_receiver_layout(self):
        code = (ROOT / "test/fixtures/morse_rx_gap_bias.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_MAX_WPM=120", "-DREQUIRE_TIGHT_PASS=1"))
        rows = [line.split("\t") for line in output.splitlines()]
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(row[2:], ["PASS", "VW MN DOG "])

    def test_former_boundaries_reproduce_the_same_tight_gap_failure(self):
        code = (ROOT / "test/fixtures/morse_rx_gap_bias.cpp").read_text(encoding="ascii")
        current = (ROOT / "src/helpers/MorseRx.h").read_text(encoding="ascii")
        letter = "gap * UnitScale >= uint32_t(gap_unit_q5) * 2UL"
        word = "gap * UnitScale >= uint32_t(gap_unit_q5) * 5UL"
        self.assertIn(letter, current)
        self.assertIn(word, current)
        former = current.replace(letter, "gap * 4UL * UnitScale >= uint32_t(gap_unit_q5) * 9UL")
        former = former.replace(word, "gap * 2UL * UnitScale >= uint32_t(gap_unit_q5) * 11UL")
        output = compile_run(self, code, flags=("-DMESH_MORSE_MAX_WPM=120", "-DREQUIRE_TIGHT_PASS=0"),
                             includes=(ROOT / "src/helpers",),
                             headers={"helpers/MorseRx.h": former})
        self.assertEqual(sum("\tFAIL\t" in line for line in output.splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
