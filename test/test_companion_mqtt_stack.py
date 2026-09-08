#!/usr/bin/env python3
"""Bound the real Companion MQTT save callback's additional stack use."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CALLBACK = "void MyMesh::onConfigBatchEnd()"
PREAMBLE = r"""
#include <helpers/MQTTPrefsStorage.h>
void reloadCompanionWiFiPowerSave();
uint8_t getCompanionWiFiPowerSave();
struct MQTTBridge { void end(); };
struct CompanionMqttSetupPortal {
  static bool saveStoredConfig(const MQTTPrefs&);
  static bool loadStoredConfig(MQTTPrefs&);
};
struct MyMesh {
  void onConfigBatchEnd();
  void syncWiFiPowerSaving();
  bool _wc_mqtt_dirty, _mqtt_started, _mqtt_configured;
  MQTTBridge* _mqtt_bridge;
  MQTTPrefs _mqtt_prefs;
};
"""


def callback_source():
    source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
    start = source.index(CALLBACK)
    return source[start:source.index("void MyMesh::execCommand", start)]


class CompanionMqttStackTests(unittest.TestCase):
    def compile_callback(self, source):
        with tempfile.TemporaryDirectory(prefix="meshcore-mqtt-stack-") as temp:
            path = Path(temp) / "callback.cpp"
            path.write_text(PREAMBLE + source)
            return subprocess.run([
                "c++", "-std=c++17", "-Os", "-fno-inline",
                "-Werror=frame-larger-than=512",
                "-DESP32=1", "-DWIFI_SSID=1", "-DWITH_MQTT_BRIDGE=1",
                "-I", str(ROOT / "src"), "-c", str(path),
                "-o", str(Path(temp) / "callback.o"),
            ], text=True, capture_output=True)

    def test_save_callback_leaves_stack_for_nvs_and_validation(self):
        # The loader already needs a full preference scratch copy. The save
        # callback must not add another one to the ESP32's 8 KB loop stack.
        result = self.compile_callback(callback_source())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_guard_rejects_the_hardware_stack_overflow_regression(self):
        source = callback_source()
        call = "CompanionMqttSetupPortal::loadStoredConfig(_mqtt_prefs)"
        self.assertIn(call, source)
        source = source.replace("{", "{\n  MQTTPrefs verified;", 1)
        source = source.replace(call, "CompanionMqttSetupPortal::loadStoredConfig(verified)")
        source = source.replace(
            "// The standalone Companion setting",
            "if (_mqtt_configured) _mqtt_prefs = verified;\n"
            "    // The standalone Companion setting",
        )
        result = self.compile_callback(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("frame size", result.stderr)


if __name__ == "__main__":
    unittest.main()
