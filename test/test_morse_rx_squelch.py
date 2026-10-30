"""Execute the optional bench RSSI floor against the real sampled decoder."""
from pathlib import Path
import unittest

from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]


class MorseRxSquelchTests(unittest.TestCase):
    def test_hil_noise_prekey_real_dot_quiet_hysteresis_and_unchanged_auto(self):
        code = (ROOT / "test/fixtures/morse_rx_squelch.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_HIL=1",))
        self.assertIn("actual squelch checks passed", output)

    def test_shipping_weak_behavior_and_layout_have_no_squelch_dependency(self):
        code = (ROOT / "test/fixtures/morse_rx_squelch.cpp").read_text(encoding="ascii")
        output = compile_run(self, code, flags=("-DMESH_MORSE_HIL=0",))
        self.assertIn("actual squelch checks passed", output)

    def test_shipping_has_no_squelch_api_or_storage(self):
        code = "#include <helpers/MorseRx.h>\nint main() { return mesh::setMorseHilSquelch(-100); }\n"
        with self.assertRaisesRegex(AssertionError, "setMorseHilSquelch.*not a member"):
            compile_run(self, code, flags=("-DMESH_MORSE_HIL=0",))


if __name__ == "__main__":
    unittest.main()
