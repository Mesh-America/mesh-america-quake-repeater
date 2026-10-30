"""Execute the private XIAO loaded-frequency override and its compile gates."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "src/helpers/CompanionStartupFrequency.h"
FLAGS = ["NRF52_PLATFORM", "NRF52840_XXAA", "XIAO_NRF52",
         "MC_XIAO_NRF52_HIL_FAST_SPI=1", "LORA_FREQ=917",
         "MESH_HIL_COMPANION_STARTUP_FREQ_MHZ=917"]


def load_site():
    source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
    begin = source[source.index("void MyMesh::begin("):
                   source.index("void MyMesh::activateRadio(")]
    start = begin.index("  const bool prefs_ready =")
    end = begin.index("  FILESYSTEM* battery_calibration_fs", start)
    return begin[start:end], begin


class CompanionHilStartupFrequency(unittest.TestCase):
    def compile(self, source, flags=(), run=False):
        with tempfile.TemporaryDirectory(prefix="companion-startup-frequency-") as folder:
            cpp = Path(folder) / "test.cpp"
            exe = Path(folder) / "test"
            cpp.write_text(source, encoding="ascii")
            result = subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17",
                "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "src"),
                *["-D" + flag for flag in flags], str(cpp), "-o", str(exe)],
                capture_output=True, text=True, timeout=30)
            if run:
                self.assertEqual(result.returncode, 0, result.stderr)
                executed = subprocess.run([str(exe)], capture_output=True,
                                          text=True, timeout=10)
                self.assertEqual(executed.returncode, 0, executed.stderr)
            return result

    def test_real_post_load_site_precedes_radio_apply_and_changes_only_frequency(self):
        site, begin = load_site()
        self.assertLess(begin.index("applyHilStartupFrequency(_prefs.freq)"),
                        begin.index("configureRadioFromPrefs();"))
        fixture = r'''
#include <helpers/CompanionStartupFrequency.h>
#include <cassert>
struct Prefs { float freq=915, bw=62.5; unsigned sf=7; bool ps=true; } _prefs;
struct { double node_lat=1, node_lon=2; } sensors;
struct Store {
  bool ready=true;
  bool loadPrefs(Prefs& value, double&, double&) {
    value.freq=910.525f; value.bw=250; value.sf=8; value.ps=false;
    return ready;
  }
} store, *_store=&store;
void loadAndApply() {
  @SITE@
  assert(prefs_ready==store.ready);
#if MESH_HIL_COMPANION_STARTUP_FREQ_MHZ
  assert(_prefs.freq==917.0f);
#else
  assert(_prefs.freq==910.525f);
#endif
  assert(_prefs.bw==250 && _prefs.sf==8 && !_prefs.ps);
  assert(sensors.node_lat==1 && sensors.node_lon==2);
}
int main() {
  loadAndApply();store.ready=false;loadAndApply();
}
'''.replace("@SITE@", site)
        self.compile(fixture, FLAGS, run=True)
        self.compile(fixture, ["LORA_FREQ=915"], run=True)

    def test_startup_override_rejects_other_boards_values_and_initial_frequencies(self):
        source = "#include <helpers/CompanionStartupFrequency.h>\nint main() {}\n"
        self.assertEqual(self.compile(source, FLAGS).returncode, 0)
        for missing in ("NRF52_PLATFORM", "NRF52840_XXAA", "XIAO_NRF52",
                        "MC_XIAO_NRF52_HIL_FAST_SPI=1", "LORA_FREQ=917"):
            with self.subTest(missing=missing):
                self.assertNotEqual(self.compile(source,
                    [flag for flag in FLAGS if flag != missing]).returncode, 0)
        for value in (1, 916, 918, -1):
            with self.subTest(value=value):
                flags = [flag for flag in FLAGS if not flag.startswith(
                    "MESH_HIL_COMPANION_STARTUP_FREQ_MHZ=")]
                flags.append(f"MESH_HIL_COMPANION_STARTUP_FREQ_MHZ={value}")
                self.assertNotEqual(self.compile(source, flags).returncode, 0)
        flags = ["LORA_FREQ=915" if flag == "LORA_FREQ=917" else flag for flag in FLAGS]
        self.assertNotEqual(self.compile(source, flags).returncode, 0)
        target = (ROOT / "variants/xiao_nrf52/XiaoRadioSpiConfig.h").read_text()
        self.assertIn("#include <helpers/CompanionStartupFrequency.h>", target)

    def test_default_off_site_has_identical_preprocessed_statements(self):
        site, _begin = load_site()
        original = site[:site.index("#if MESH_HIL_COMPANION_STARTUP_FREQ_MHZ")]
        def preprocess(text):
            result = subprocess.run([os.environ.get("CXX", "c++"), "-E", "-P",
                "-x", "c++", "-I", str(ROOT / "src"), "-"],
                input=text, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return re.sub(r"\s+", "", result.stdout)
        self.assertEqual(preprocess(original), preprocess(
            "#include <helpers/CompanionStartupFrequency.h>\n" + site))


if __name__ == "__main__":
    unittest.main()
