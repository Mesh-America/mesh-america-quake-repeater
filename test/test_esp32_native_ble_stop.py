#!/usr/bin/env python3
"""Execute the native Arduino NimBLE stop path, including failed host init.

The production teardown methods are compiled unchanged. The doubles model the
native wrapper's host-task lifecycle and ignored controller teardown failures.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


HARNESS = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <vector>
using esp_err_t = int;
constexpr int ESP_OK = 0;
enum esp_bt_controller_status_t { ESP_BT_CONTROLLER_STATUS_IDLE,
    ESP_BT_CONTROLLER_STATUS_INITED, ESP_BT_CONTROLLER_STATUS_ENABLED };
static auto controller = ESP_BT_CONTROLLER_STATUS_IDLE;
static bool initialized = false, host_task_created = false, host_running = false;
static bool fail_host_stop = false, fail_controller_stop = false;
static bool fail_controller_deinit = false;
static unsigned native_stops = 0, wrapper_deinits = 0, objects = 0;
static unsigned controller_stops = 0, controller_deinits = 0;
int nimble_port_stop() {
  // A failed BLEDevice::init can precede host task/lock creation. Calling the
  // real SDK stop in that state is unsafe; the production gate must skip it.
  assert(host_task_created && initialized);
  ++native_stops;
  if (fail_host_stop) return 1;
  if (!host_running) return 8; // BLE_HS_EALREADY on the wrapper's second call.
  host_running = false;
  return 0;
}
esp_bt_controller_status_t esp_bt_controller_get_status() { return controller; }
int esp_bt_controller_disable() {
  ++controller_stops;
  if (fail_controller_stop) return 1;
  controller = ESP_BT_CONTROLLER_STATUS_INITED;
  return ESP_OK;
}
int esp_bt_controller_deinit() {
  ++controller_deinits;
  if (fail_controller_deinit) return 1;
  controller = ESP_BT_CONTROLLER_STATUS_IDLE;
  return ESP_OK;
}
struct GattObject {
  GattObject() { ++objects; }
  ~GattObject() { assert(!host_running); --objects; }
};
using BLEServer = GattObject;
using BLEService = GattObject;
using BLECharacteristic = GattObject;
using BLE2902 = GattObject;
static BLEServer* library_server = nullptr;
static std::vector<GattObject*> library_children;
struct BLEDevice {
  static bool getInitialized() { return initialized; }
  static BLEServer* getServer() { return library_server; }
  static void deinit(bool release) {
    assert(!release); // No irreversible controller-memory release.
    if (!initialized) return;
    ++wrapper_deinits;
    // The current native wrapper deletes the server before stopping its port.
    // The adapter must have stopped callback dispatch before entering here.
    for (auto* child : library_children) delete child;
    library_children.clear();
    delete library_server; library_server = nullptr;
    (void)nimble_port_stop();
    initialized = host_task_created = false;
    // Model its ignored controller teardown error. The adapter must verify
    // the physical state independently after this wrapper reports stopped.
    if (esp_bt_controller_disable() == ESP_OK) (void)esp_bt_controller_deinit();
  }
};
@OWNERSHIP@
@CONTROLLER_STOP@
class SerialBLEInterface {
public:
  std::atomic<bool> _callbacksEnabled{true};
  bool _nativeHostStopped = false;
  bool _advertisingConfigured = true;
  BLEServer* pServer = nullptr;
  BLEService* pService = nullptr;
  BLECharacteristic* pTxCharacteristic = nullptr;
  BLECharacteristic* pRxCharacteristic = nullptr;
  BLE2902* pTxDescriptor = nullptr;
  bool stopBluetoothStack();
  void startHost() {
    assert(objects == 0);
    initialized = host_task_created = host_running = true;
    controller = ESP_BT_CONTROLLER_STATUS_ENABLED;
    pServer = library_server = new BLEServer;
    pService = new BLEService;
    pTxCharacteristic = new BLECharacteristic;
    pRxCharacteristic = new BLECharacteristic;
    pTxDescriptor = new BLE2902;
    library_children = {pService};
  }
};
@STACK_STOP@
static void reset() {
  assert(objects == 0 && library_server == nullptr);
  initialized = host_task_created = host_running = false;
  fail_host_stop = fail_controller_stop = fail_controller_deinit = false;
  native_stops = wrapper_deinits = controller_stops = controller_deinits = 0;
  controller = ESP_BT_CONTROLLER_STATUS_IDLE;
}
int main() {
  // Initialization failed before creating a native host task. The controller
  // may nevertheless need cleanup, without touching uninitialized host locks.
  for (auto partial : {ESP_BT_CONTROLLER_STATUS_IDLE,
                       ESP_BT_CONTROLLER_STATUS_INITED,
                       ESP_BT_CONTROLLER_STATUS_ENABLED}) {
    reset(); SerialBLEInterface adapter; controller = partial;
    assert(adapter.stopBluetoothStack());
    assert(native_stops == 0 && wrapper_deinits == 0);
    assert(controller == ESP_BT_CONTROLLER_STATUS_IDLE);
    assert(!adapter._callbacksEnabled.load() && objects == 0);
  }
  reset(); SerialBLEInterface normal; normal.startHost();
  assert(normal.stopBluetoothStack());
  assert(native_stops == 2 && wrapper_deinits == 1 && objects == 0);
  assert(!initialized && !host_task_created && !host_running);
  assert(controller == ESP_BT_CONTROLLER_STATUS_IDLE && normal.pServer == nullptr);

  reset(); SerialBLEInterface failed_host; failed_host.startHost();
  fail_host_stop = true;
  assert(!failed_host.stopBluetoothStack());
  assert(objects == 5 && initialized && host_running && wrapper_deinits == 0);
  fail_host_stop = false;
  assert(failed_host.stopBluetoothStack()); assert(objects == 0);

  for (bool deinit_failure : {false, true}) {
    reset(); SerialBLEInterface partial; partial.startHost();
    fail_controller_stop = !deinit_failure;
    fail_controller_deinit = deinit_failure;
    assert(!partial.stopBluetoothStack());
    assert(!initialized && !host_task_created && partial._nativeHostStopped);
    assert(objects == 0 && controller != ESP_BT_CONTROLLER_STATUS_IDLE);
    const unsigned stopped = native_stops;
    fail_controller_stop = fail_controller_deinit = false;
    assert(partial.stopBluetoothStack());
    assert(native_stops == stopped); // No native host task remains to stop.
    assert(controller == ESP_BT_CONTROLLER_STATUS_IDLE && objects == 0);
  }
  puts("native NimBLE failed-init and teardown cases passed");
}
'''


class NativeNimbleStopTests(unittest.TestCase):
    def test_production_stop_handles_absent_and_started_host_tasks(self):
        source = (ROOT / "src/helpers/esp32/SerialBLEInterface.cpp").read_text()
        ownership_start = source.index("template <typename Device,")
        ownership = source[ownership_start:source.index("\n#endif", ownership_start)]
        harness = HARNESS.replace("@OWNERSHIP@", ownership).replace(
            "@CONTROLLER_STOP@", function(source, "static bool stopBluetoothController()"))
        harness = harness.replace("@STACK_STOP@", function(
            source, "bool SerialBLEInterface::stopBluetoothStack()"))
        with tempfile.TemporaryDirectory(prefix="mesh-native-nimble-stop-") as directory:
            cpp, exe = Path(directory) / "stop.cpp", Path(directory) / "stop"
            cpp.write_text(harness)
            built = subprocess.run([
                os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-DCONFIG_NIMBLE_ENABLED=1",
                str(cpp), "-o", str(exe)], text=True, capture_output=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(exe)], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("failed-init and teardown cases passed", result.stdout)
            # Prove the failed-init fixture detects the original unsafe stop.
            broken = harness.replace("!_nativeHostStopped && BLEDevice::getInitialized()",
                                     "!_nativeHostStopped")
            cpp.write_text(broken)
            built = subprocess.run([
                os.environ.get("CXX", "c++"), "-std=c++17", "-DCONFIG_NIMBLE_ENABLED=1",
                str(cpp), "-o", str(exe)], text=True, capture_output=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(exe)], text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("host_task_created && initialized", result.stderr)


if __name__ == "__main__":
    unittest.main()
