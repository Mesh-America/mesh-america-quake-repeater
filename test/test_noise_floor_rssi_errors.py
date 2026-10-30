"""Execute each LR instantaneous-RSSI method against failed hardware reads."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def rssi_method(header):
    start = header.index("float getCurrentRSSI() override {")
    end = header.index("\n  }", start) + len("\n  }")
    return header[start:end]


class NoiseFloorRssiErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("RSSI error tests require a host C++ compiler")
        cls.work = tempfile.TemporaryDirectory(prefix="meshcore-rssi-errors-")
        cls.addClassCleanup(cls.work.cleanup)
        binary = Path(cls.work.name) / ("rssi.exe" if os.name == "nt" else "rssi")
        classes = []
        for family in ("LR1110", "LR1121", "LR2021"):
            name = "Custom" + family + "Wrapper"
            source = (ROOT / ("src/helpers/radiolib/" + name + ".h")).read_text()
            classes.append("class " + name + " : public WrapperBase { public: "
                           + rssi_method(source) + " };\n")
        harness = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include "helpers/radiolib/NoiseFloorEstimator.h"
constexpr int RADIOLIB_ERR_NONE = 0;
struct FakeRadio {
  int status = 0;
  float rssi = -119.25f;
  bool write_value = true;
  int getRssiInst(float* value) {
    if (write_value) *value = rssi;
    return status;
  }
};
using CustomLR1110 = FakeRadio;
using CustomLR1121 = FakeRadio;
using CustomLR2021 = FakeRadio;
struct WrapperBase {
  FakeRadio radio;
  FakeRadio* _radio = &radio;
  virtual ~WrapperBase() = default;
  virtual float getCurrentRSSI() = 0;
};
@CLASSES@
template<class Wrapper> void exercise() {
  Wrapper wrapper;
  assert(wrapper.getCurrentRSSI() == -119.25f);
  for (int status : {-1, -2, -16, 1}) {
    wrapper.radio.status = status;
    for (bool write : {false, true}) {
      wrapper.radio.write_value = write;
      NoiseFloorEstimator estimator;
      for (unsigned sample = 0; sample < NoiseFloorEstimator::SAMPLE_COUNT; ++sample) {
        const float rssi = wrapper.getCurrentRSSI();
        assert(isnan(rssi));
        assert(!estimator.add(rssi, sample * NoiseFloorEstimator::SAMPLE_INTERVAL_MS));
      }
      assert(estimator.count() == 0 && !estimator.complete());
      int32_t floor = -12000;
      assert(!estimator.publish(floor, false));
      assert(floor == -12000);
    }
  }
  wrapper.radio.status = 0;
  wrapper.radio.write_value = false;
  assert(isnan(wrapper.getCurrentRSSI()));
  wrapper.radio.write_value = true;
  assert(wrapper.getCurrentRSSI() == -119.25f);
  NoiseFloorEstimator estimator;
  for (unsigned sample = 0; sample < NoiseFloorEstimator::SAMPLE_COUNT; ++sample) {
    assert(estimator.add(wrapper.getCurrentRSSI(), sample * NoiseFloorEstimator::SAMPLE_INTERVAL_MS));
  }
  int32_t floor = 0;
  assert(estimator.publish(floor, false) && floor == -11925);
}
int main() {
  exercise<CustomLR1110Wrapper>();
  exercise<CustomLR1121Wrapper>();
  exercise<CustomLR2021Wrapper>();
}
'''.replace("@CLASSES@", "\n".join(classes))
        harness = harness.replace("#include <stdint.h>", "#include <stdint.h>\n#include <initializer_list>")
        source = Path(cls.work.name) / "rssi.cpp"
        source.write_text(harness, encoding="ascii")
        flags = ["-std=c++11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                      "-fno-pie", "-no-pie"]
        built = subprocess.run([compiler, *flags, "-I" + str(ROOT / "src"),
                                str(source), "-o", str(binary)],
                               capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)
        cls.binary = binary

    def test_failed_reads_cannot_fabricate_noise_floor_samples(self):
        result = subprocess.run([str(self.binary)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
