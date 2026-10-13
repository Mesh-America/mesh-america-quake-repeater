"""Execute the real fractional Morse timing without hardware or PlatformIO."""
from pathlib import Path
import unittest

from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]


class MorseRxTimingTests(unittest.TestCase):
    def test_actual_q5_drift_classification_bounds_fractional_gaps_rollover_and_size(self):
        code = (ROOT / "test/fixtures/morse_rx_timing.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_MAX_WPM=240", "-DMESH_MORSE_HIL=0"))
        self.assertIn("Q5 timing checks passed; MorseRx size: 4168 bytes", output)

    def test_hil_fast_off_keeps_the_same_fractional_timing_and_allocation_layout(self):
        code = (ROOT / "test/fixtures/morse_rx_timing.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_MAX_WPM=240", "-DMESH_MORSE_HIL=1",
                                               "-DMESH_MORSE_HIL_FAST_OFF_DEBOUNCE=1"))
        self.assertIn("Q5 timing checks passed", output)


if __name__ == "__main__":
    unittest.main()
