"""Unused TFT fonts are omitted without altering the selected hardware setup."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "fixtures" / "nrf52_tft_trim"


class Nrf52TftFontTrimTest(unittest.TestCase):
    def test_selected_setup_and_current_font_survive(self):
        cases = (
            ([], False),
            (["-DNRF52_PLATFORM=1"], False),
            (["-DMESH_NRF52_FLASH_TRIM=1"], False),
            (["-DNRF52_PLATFORM=1", "-DMESH_NRF52_FLASH_TRIM=0"], False),
            (["-DNRF52_PLATFORM=1", "-DMESH_NRF52_FLASH_TRIM=1"], True),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for flags, trimmed in cases:
                with self.subTest(flags=flags):
                    executable = Path(temp_dir) / "font_scope"
                    subprocess.run([
                        "c++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        *flags, f"-DEXPECT_TRIM={int(trimmed)}",
                        f"-I{FIXTURES}", f"-I{ROOT / 'src'}",
                        str(FIXTURES / "test.cpp"), "-o", str(executable),
                    ], check=True)
                    subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
