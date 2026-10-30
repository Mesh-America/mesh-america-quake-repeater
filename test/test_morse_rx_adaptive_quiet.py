"""Exercise adaptive quiet rejection in the actual shipping RSSI decoder."""
from pathlib import Path
import unittest

from test_morse_tx import compile_run

ROOT = Path(__file__).resolve().parents[1]


class MorseRxAdaptiveQuietTests(unittest.TestCase):
    def test_learned_excursions_weak_cw_expiry_restart_and_rollover(self):
        code = (ROOT / "test/fixtures/morse_rx_adaptive_quiet.cpp").read_text(encoding="ascii")
        for hil in (0, 1):
            with self.subTest(hil=hil):
                output = compile_run(self, code, flags=(f"-DMESH_MORSE_HIL={hil}",))
                self.assertIn("actual adaptive quiet checks passed", output)

    def test_mean_only_negative_control_reproduces_noise_prekey(self):
        code = (ROOT / "test/fixtures/morse_rx_adaptive_quiet.cpp").read_text(encoding="ascii")
        source = (ROOT / "src/helpers/MorseRx.h").read_text(encoding="ascii")
        gate = "    if (threshold < quiet_threshold) threshold = quiet_threshold;\n"
        self.assertEqual(source.count(gate), 1)
        old = source.replace(gate, "    (void)quiet_threshold;\n")
        with self.assertRaisesRegex(AssertionError, "Assertion|assert"):
            compile_run(self, code, flags=("-DMESH_MORSE_HIL=0",),
                        headers={"helpers/MorseRx.h": old,
                                 "helpers/MorseTx.h": (ROOT / "src/helpers/MorseTx.h").read_text(encoding="ascii")})


if __name__ == "__main__":
    unittest.main()
