"""Exercise the Sensor example's actual battery callback with absent readings."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <vector>
using std::isfinite;
namespace mesh {
struct MainBoard {};
struct Radio {};
struct MillisecondClock {};
struct RNG {};
struct RTCClock {};
struct MeshTables {};
}
constexpr uint8_t TELEM_CHANNEL_SELF = 0;
constexpr uint8_t LPP_VOLTAGE = 2;
struct MinMaxAvg {};
struct TimeSeriesData {
  std::vector<float> values;
  TimeSeriesData(int, int) {}
  void recordData(mesh::RTCClock*, float voltage) { values.push_back(voltage); }
  void calcMinMaxAvg(mesh::RTCClock*, uint32_t, uint32_t,
                    MinMaxAvg*, uint8_t, uint8_t) {}
};
struct SensorMesh {
  enum AlertPriority { LOW_PRI_ALERT, HIGH_PRI_ALERT };
  struct Trigger { bool active = false; };
  float voltage = 0;
  mesh::RTCClock clock;
  SensorMesh(mesh::MainBoard&, mesh::Radio&, mesh::MillisecondClock&,
             mesh::RNG&, mesh::RTCClock&, mesh::MeshTables&) {}
  virtual ~SensorMesh() = default;
  virtual void onSensorDataRead() = 0;
  virtual int querySeriesData(uint32_t, uint32_t, MinMaxAvg*, int) = 0;
  virtual bool handleCustomCommand(uint32_t, char*, char*) = 0;
  float getVoltage(uint8_t channel) {
    assert(channel == TELEM_CHANNEL_SELF);
    return voltage;
  }
  mesh::RTCClock* getRTCClock() { return &clock; }
  void alertIf(bool condition, Trigger& trigger, AlertPriority, const char*) {
    trigger.active = condition;
  }
};
// PRODUCTION_CLASS
struct TestMesh : MyMesh {
  using MyMesh::MyMesh;
  using MyMesh::onSensorDataRead;
  using MyMesh::battery_data;
  using MyMesh::critical_batt;
  using MyMesh::low_batt;
};
int main(int argc, char** argv) {
  assert(argc == 2);
  mesh::MainBoard board;
  mesh::Radio radio;
  mesh::MillisecondClock milliseconds;
  mesh::RNG random;
  mesh::RTCClock clock;
  mesh::MeshTables tables;
  TestMesh sensor(board, radio, milliseconds, random, clock, tables);
  const auto read = [&](float voltage) {
    sensor.voltage = voltage;
    sensor.onSensorDataRead();
  };
  if (strcmp(argv[1], "unavailable") == 0) {
    // Zero is the board API's unsupported measurement and the missing-field
    // fallback. Neither is a discharged battery. Keep history cadence intact.
    read(0.0f);
    assert(!sensor.critical_batt.active && !sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 1);
    assert(sensor.battery_data.values[0] == 0.0f);
  } else if (strcmp(argv[1], "invalid") == 0) {
    for (float voltage : {-1.0f, std::numeric_limits<float>::quiet_NaN(),
                          std::numeric_limits<float>::infinity(),
                          -std::numeric_limits<float>::infinity()}) {
      read(voltage);
      assert(!sensor.critical_batt.active && !sensor.low_batt.active);
    }
    assert(sensor.battery_data.values.size() == 4);
  } else if (strcmp(argv[1], "healthy") == 0) {
    read(4.1f);
    assert(!sensor.critical_batt.active && !sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 1);
    assert(sensor.battery_data.values[0] == 4.1f);
  } else if (strcmp(argv[1], "low") == 0) {
    read(3.5f);
    assert(!sensor.critical_batt.active && sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 1);
  } else if (strcmp(argv[1], "critical") == 0) {
    read(3.3f);
    assert(sensor.critical_batt.active && sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 1);
  } else if (strcmp(argv[1], "boundaries") == 0) {
    read(3.4f);
    assert(!sensor.critical_batt.active && sensor.low_batt.active);
    read(3.6f);
    assert(!sensor.critical_batt.active && !sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 2);
  } else if (strcmp(argv[1], "lost_measurement") == 0) {
    read(3.3f);
    assert(sensor.critical_batt.active && sensor.low_batt.active);
    read(0.0f);
    assert(!sensor.critical_batt.active && !sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 2);
    assert(sensor.battery_data.values[1] == 0.0f);
    read(3.3f);
    assert(sensor.critical_batt.active && sensor.low_batt.active);
    assert(sensor.battery_data.values.size() == 3);
  } else {
    assert(false && "unknown case");
  }
}
'''


class SensorBatteryAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise RuntimeError("host C++ compiler required")
        source = (ROOT / "examples/simple_sensor/main.cpp").read_text()
        start = source.index("class MyMesh : public SensorMesh {")
        end = source.index("\n};", start) + len("\n};")
        cls.directory = tempfile.TemporaryDirectory(prefix="sensor-battery-")
        cls.addClassCleanup(cls.directory.cleanup)
        work = Path(cls.directory.name)
        harness = work / "test.cpp"
        harness.write_text(HARNESS.replace("// PRODUCTION_CLASS", source[start:end]))
        cls.binary = work / "test"
        compiled = subprocess.run([
            compiler, "-std=c++11", "-Wall", "-Wextra", "-Wno-unused-parameter",
            str(harness), "-o", str(cls.binary),
        ], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, case):
        completed = subprocess.run([str(self.binary), case],
                                   capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_unsupported_or_missing_voltage(self):
        self.run_case("unavailable")

    def test_invalid_voltage(self):
        self.run_case("invalid")

    def test_healthy_voltage(self):
        self.run_case("healthy")

    def test_low_battery(self):
        self.run_case("low")

    def test_critical_battery(self):
        self.run_case("critical")

    def test_existing_threshold_boundaries(self):
        self.run_case("boundaries")

    def test_invalid_reading_clears_pending_alarm_and_preserves_history_cadence(self):
        self.run_case("lost_measurement")


if __name__ == "__main__":
    unittest.main()
