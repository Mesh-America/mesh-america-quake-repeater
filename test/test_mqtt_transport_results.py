#!/usr/bin/env python3
"""Compile the real adapter/bridge attempt methods against controllable SDK calls.

No PlatformIO/network/hardware is used. IDF4 and IDF5 config layouts are covered.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def method(path, signature):
    source = (ROOT / path).read_text(encoding="utf-8")
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    pos = opening + 1
    while depth:
        depth += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[start:pos] + "\n"


PREAMBLE = r'''
#include <cstdlib>
#include <cstdint>
#include <cassert>
#include <functional>
#include "helpers/MQTTConnectionHealth.h"
using esp_err_t = int;
using esp_mqtt_client_handle_t = void*;
constexpr int ESP_OK=0, ESP_FAIL=-1, ESP_ERR_INVALID_STATE=2, ESP_ERR_NO_MEM=3;
constexpr int ESP_ERR_INVALID_ARG=4, MQTT_EVENT_ANY=0, RUNTIME_MQTT_SLOTS=2;
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_ERROR_CHECK_WITHOUT_ABORT(...) ((void)0)
#define MQTT_DEBUG_PRINTLN(...) ((void)0)
const char* esp_err_to_name(int) { return "mock"; }
struct Config {
  struct { struct { const char* uri=nullptr; } address; } broker;
  struct { int size=1024; } buffer;
  const char* uri=nullptr;
  int buffer_size=1024;
};
static bool fail_malloc=false, fail_init=false;
static int register_result=ESP_OK, config_result=ESP_OK;
static int start_result=ESP_OK, reconnect_result=ESP_OK;
static int init_calls=0, register_calls=0, destroy_calls=0, config_calls=0;
static int start_calls=0, reconnect_calls=0;
static std::function<void()> sdk_callback;
void* test_malloc(size_t size) { return fail_malloc ? nullptr : std::malloc(size); }
#define malloc test_malloc
void* esp_mqtt_client_init(Config*) {
  ++init_calls; return fail_init ? nullptr : reinterpret_cast<void*>(1);
}
int esp_mqtt_client_register_event(void*, int, void(*)(void*,int,int,void*), void*) {
  ++register_calls; return register_result;
}
int esp_mqtt_client_destroy(void*) { ++destroy_calls; return ESP_OK; }
int esp_mqtt_set_config(void*, Config*) { ++config_calls; return config_result; }
int esp_mqtt_client_start(void*) {
  ++start_calls; if(sdk_callback) sdk_callback(); return start_result;
}
int esp_mqtt_client_reconnect(void*) {
  ++reconnect_calls; if(sdk_callback) sdk_callback(); return reconnect_result;
}
struct PsychicMqttClient {
  Config _mqtt_cfg;
  void* _client=nullptr;
  bool _config_dirty=true, _started=false;
  char* _buffer=nullptr;
  size_t _buffer_capacity=0;
  ~PsychicMqttClient() { std::free(_buffer); }
  static void _onMqttEventStatic(void*,int,int,void*) {}
  esp_err_t applyConfig();
  esp_err_t connect();
  esp_err_t reconnect();
  bool isStarted() const { return _started; }
  void uri(const char* uri) { _mqtt_cfg.uri=uri; _mqtt_cfg.broker.address.uri=uri; }
};
struct MQTTBridge {
  struct MQTTSlot {
    PsychicMqttClient* client=nullptr;
    uint32_t start_failures=0;
  };
  MQTTSlot _slots[RUNTIME_MQTT_SLOTS];
  volatile bool _slot_attempt_pending[RUNTIME_MQTT_SLOTS] = {};
  esp_err_t reconnectSlotClient(int index);
};
'''

MAIN = r'''
int main() {
  PsychicMqttClient c;
  assert(c.connect()==ESP_ERR_INVALID_STATE && start_calls==0 && init_calls==0);
  c.uri("mqtts://broker");
  std::free(c._buffer); c._buffer=nullptr;
  fail_malloc=true;
  assert(c.connect()==ESP_ERR_NO_MEM && start_calls==0 && init_calls==0);
  fail_malloc=false;
  fail_init=true;
  assert(c.connect()==ESP_ERR_NO_MEM && register_calls==0 && start_calls==0);
  fail_init=false;
  register_result=ESP_FAIL;
  assert(c.connect()==ESP_FAIL && c._client==nullptr && c._config_dirty);
  assert(destroy_calls==1 && start_calls==0);
  register_result=ESP_OK;
  start_result=ESP_FAIL;
  assert(c.connect()==ESP_FAIL && !c.isStarted());
  start_result=ESP_OK;
  assert(c.connect()==ESP_OK && c.isStarted());
  assert(register_calls==2); // failed registration then one successful registration
  c._config_dirty=true;
  config_result=ESP_FAIL;
  int starts=start_calls;
  assert(c.connect()==ESP_FAIL && start_calls==starts && c._config_dirty);
  assert(c.reconnect()==ESP_FAIL && reconnect_calls==0 && c._config_dirty);
  config_result=ESP_OK;
  reconnect_result=ESP_FAIL;
  assert(c.reconnect()==ESP_FAIL && !c._config_dirty && reconnect_calls==1);
  reconnect_result=ESP_OK;
  assert(c.reconnect()==ESP_OK && reconnect_calls==2);

  MQTTBridge b;
  assert(b.reconnectSlotClient(-1)==ESP_ERR_INVALID_ARG);
  assert(b.reconnectSlotClient(1)==ESP_ERR_INVALID_STATE);
  b._slots[0].client=&c;
  reconnect_result=ESP_FAIL;
  assert(b.reconnectSlotClient(0)==ESP_FAIL);
  assert(!b._slot_attempt_pending[0] && b._slots[0].start_failures==0);
  b._slot_attempt_pending[0]=true;
  assert(b.reconnectSlotClient(0)==ESP_FAIL);
  assert(b._slot_attempt_pending[0] && b._slots[0].start_failures==0);
  sdk_callback=[&]() { b._slot_attempt_pending[0]=false; };
  assert(b.reconnectSlotClient(0)==ESP_FAIL && !b._slot_attempt_pending[0]);
  sdk_callback=nullptr;
  c._started=false;
  start_result=ESP_FAIL;
  assert(b.reconnectSlotClient(0)==ESP_FAIL);
  assert(!b._slot_attempt_pending[0] && b._slots[0].start_failures==1);
  start_result=ESP_OK;
  sdk_callback=[&]() {
    assert(b._slot_attempt_pending[0]); // set before synchronous SDK callback
    b._slot_attempt_pending[0]=false;   // onConnect completes the attempt
  };
  assert(b.reconnectSlotClient(0)==ESP_OK && !b._slot_attempt_pending[0]);
  sdk_callback=nullptr;
  reconnect_result=ESP_OK;
  assert(b.reconnectSlotClient(0)==ESP_OK && b._slot_attempt_pending[0]);
  return 0;
}
'''


class MqttTransportResultsTests(unittest.TestCase):
    def test_real_adapter_and_bridge_methods_for_both_idf_layouts(self):
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(compiler, "a host C++ compiler is required")
        adapter = "lib/PsychicMqttClient/src/PsychicMqttClient.cpp"
        source = PREAMBLE + "\n".join(method(adapter, signature) for signature in (
            "esp_err_t PsychicMqttClient::applyConfig()",
            "esp_err_t PsychicMqttClient::connect()",
            "esp_err_t PsychicMqttClient::reconnect()"))
        source += method("src/helpers/bridges/MQTTBridge.cpp",
                         "esp_err_t MQTTBridge::reconnectSlotClient(int index)") + MAIN
        with tempfile.TemporaryDirectory(prefix="meshcore-mqtt-results-") as temp:
            path = Path(temp) / "results.cpp"
            path.write_text(source, encoding="utf-8")
            for major in (4, 5):
                with self.subTest(idf_major=major):
                    exe = Path(temp) / (f"results-{major}" + (".exe" if os.name == "nt" else ""))
                    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                                             f"-DESP_IDF_VERSION_MAJOR={major}",
                                             "-I", str(ROOT / "src"), str(path), "-o", str(exe)],
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(exe)], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_attempt_wiring_covers_stop_bounce_setup_and_both_status_paths(self):
        source = (ROOT / "src/helpers/bridges/MQTTBridge.cpp").read_text(encoding="utf-8")
        self.assertEqual(source.count("result = slot.client->connect();"), 1)
        self.assertEqual(source.count("result = slot.client->reconnect();"), 1)
        self.assertEqual(source.count("repeatStatus(), collectConnHealth()"), 2)
        for signature in ("void MQTTBridge::teardownSlot(", "void MQTTBridge::destroySlotClients("):
            body = method("src/helpers/bridges/MQTTBridge.cpp", signature)
            self.assertIn("_slot_attempt_pending[", body)
            self.assertNotIn("connect_failures =", body)
            self.assertNotIn("start_failures =", body)
        callback = source[source.index("slot.client->onDisconnect("):source.index("slot.client->onError(")]
        self.assertIn("disconnectFailedAttempt", callback)
        self.assertIn("incrementFailures", callback)
        stats = method("src/helpers/bridges/MQTTBridge.cpp", "void MQTTBridge::formatMqttStatsReply(")
        self.assertEqual(stats.count("MQTTConnectionHealth::isOutageSlot("), 2)


if __name__ == "__main__":
    unittest.main()
