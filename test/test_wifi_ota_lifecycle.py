"""Execute production WiFi ownership, ESP-NOW cleanup and ElegantOTA startup.

Desired-behavior assertions are marked as known failures until firmware is fixed. Set
MESHCORE_REQUIRE_WIFI_OTA_FIX=1 to make those regressions ordinary failures.
Compilation, every fixture execution and observation parsing happen in
setUpClass, outside expectedFailure, so infrastructure failures cannot pass.
OTA startup coverage deliberately selects ElegantOTA, not LightweightOTA.
"""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

from test_radio_receive_contract import method


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = (
    "owners_none", "owners_web", "owners_mqtt", "owners_espnow", "owners_httpota",
    "owners_httpota_sta", "cleanup_none", "cleanup_web", "cleanup_mqtt", "cleanup_espnow",
    "cleanup_httpota", "cleanup_httpota_sta",
    "ota_ap_fresh", "ota_ap_repeat", "ota_sta_repeat", "ota_stale_ap", "ota_ap_failure",
)

STUBS = r'''
#include <helpers/WirelessControl.h>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

#define ESP32 1
#define WITH_WEBCONFIG 1
#define WITH_MQTT_BRIDGE 1
#define WITH_ESPNOW_BRIDGE 1
#define MESH_DEBUG_PRINTLN(...) ((void)0)
constexpr int WL_CONNECTED = 3, WL_DISCONNECTED = 6, HTTP_GET = 0;

struct IPAddress {
  uint32_t value = 0;
  IPAddress() = default;
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d)
      : value((uint32_t(a) << 24) | (uint32_t(b) << 16) | (uint32_t(c) << 8) | d) {}
  std::string toString() const {
    char text[16];
    std::snprintf(text, sizeof(text), "%u.%u.%u.%u", (value >> 24) & 255,
                  (value >> 16) & 255, (value >> 8) & 255, value & 255);
    return text;
  }
};

// Raw SDK lifecycle is separate from Arduino's cached initialization state.
// A raw stop/deinit must not magically update wrapper caches or ota_server.
bool sdk_initialized = false, sdk_started = false, sdk_ap_active = false;
struct MockWiFi {
  int station_status = WL_DISCONNECTED, ap_start_calls = 0;
  bool ap_config_ok = true, ap_start_ok = true;
  bool initialized_cache = false, started_cache = false;
  IPAddress station_ip, ap_ip, configured_ap_ip;
  int status() const { return station_status; }
  IPAddress localIP() const { return station_ip; }
  IPAddress softAPIP() const { return ap_ip; }
  bool softAPConfig(IPAddress ip, IPAddress, IPAddress) {
    configured_ap_ip = ip;
    return ap_config_ok;
  }
  bool softAP(const char*, const char*) {
    ++ap_start_calls;
    if (ap_start_ok) {
      sdk_initialized = sdk_started = sdk_ap_active = true;
      initialized_cache = started_cache = true;
      ap_ip = configured_ap_ip;
    }
    return ap_start_ok;
  }
} WiFi;

int wifi_stop_calls = 0, wifi_deinit_calls = 0;
int esp_wifi_stop() {
  ++wifi_stop_calls;
  sdk_started = sdk_ap_active = false;
  WiFi.station_status = WL_DISCONNECTED;
  WiFi.station_ip = IPAddress();
  WiFi.ap_ip = IPAddress();
  return 0;
}
int esp_wifi_deinit() { ++wifi_deinit_calls; sdk_initialized = false; return 0; }

int server_count = 0, server_begin_calls = 0;
struct AsyncWebServerRequest {
  template<class... Args> void send(Args...) {}
};
struct AsyncWebServer {
  explicit AsyncWebServer(int port) { assert(port == 80); ++server_count; }
  template<class Handler> void on(const char*, int, Handler) {}
  void begin() { ++server_begin_calls; }
};
struct MockElegantOTA {
  void setID(const char*) {}
  void begin(AsyncWebServer* server) { assert(server != nullptr); }
} AsyncElegantOTA;
struct MockSPIFFS {} SPIFFS;

class ESP32Board {
public:
  bool inhibit_sleep = false;
  AsyncWebServer* ota_server = nullptr;
  ~ESP32Board() { delete ota_server; }
  const char* getManufacturerName() const { return "test board"; }
  bool startOTAUpdate(const char* id, char reply[], bool force_ap);
  @OTA_RUNNING@
} board;

struct MockMesh {
  bool web = false, mqtt = false, espnow = false;
  bool isWebConfigActive() const { return web; }
  bool isMqttBridgeRunning() const { return mqtt; }
  bool isEspNowBridgeRunning() const { return espnow; }
} the_mesh;

// Only platform endpoints are mocked: enabled() and the controller facade
// below are production, never a hard-coded "WiFi owns everything" backend.
class InfrastructureWirelessBackend : public mesh::wireless::Backend {
public:
  uint8_t available() const override { return mesh::wireless::WiFi | mesh::wireless::EspNow; }
  @ENABLED@
  uint8_t clients() const override { return mesh::wireless::Independent; }
  mesh::wireless::Result set(uint8_t, bool) override { return mesh::wireless::Result::Done; }
};

@CLEANUP@
@START_OTA@
'''

CHECKS = r'''
void seedStation() {
  sdk_initialized = sdk_started = true;
  WiFi.initialized_cache = WiFi.started_cache = true;
  WiFi.station_status = WL_CONNECTED;
  WiFi.station_ip = IPAddress(10, 0, 0, 7);
}
bool endpointUsable() {
  return sdk_initialized && sdk_started
      && ((WiFi.station_status == WL_CONNECTED && WiFi.station_ip.value != 0)
          || (sdk_ap_active && WiFi.ap_ip.value != 0));
}
int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  InfrastructureWirelessBackend backend;
  mesh::wireless::control().begin(backend);
  char reply[160] = {};
  bool first_started = false, started = false;

  if (scenario == "owners_web" || scenario == "cleanup_web") {
    the_mesh.web = true;
    const IPAddress ip(192, 168, 4, 1), mask(255, 255, 255, 0);
    assert(WiFi.softAPConfig(ip, ip, mask) && WiFi.softAP("setup", nullptr));
    assert(endpointUsable());
  } else if (scenario == "owners_mqtt" || scenario == "cleanup_mqtt") {
    the_mesh.mqtt = true;
    seedStation();
    assert(endpointUsable());
  } else if (scenario == "owners_espnow" || scenario == "cleanup_espnow") {
    the_mesh.espnow = true;
    seedStation();
  }
  else if (scenario == "owners_httpota" || scenario == "cleanup_httpota"
           || scenario == "owners_httpota_sta" || scenario == "cleanup_httpota_sta"
           || scenario == "ota_ap_fresh" || scenario == "ota_ap_repeat"
           || scenario == "ota_sta_repeat" || scenario == "ota_stale_ap") {
    if (scenario == "ota_sta_repeat" || scenario == "owners_httpota_sta"
        || scenario == "cleanup_httpota_sta") seedStation();
    first_started = board.startOTAUpdate("test", reply, false);
    // Preconditions for fault injection are checked before expectedFailure.
    assert(first_started && board.isOTAUpdateRunning());
    assert(!the_mesh.web && !the_mesh.mqtt);
    assert(endpointUsable() && sdk_initialized && sdk_started);
    assert(WiFi.initialized_cache && WiFi.started_cache);
    assert(std::strstr(reply, "0.0.0.0") == nullptr);
    assert(server_count == 1 && server_begin_calls == 1);
    started = first_started;
  } else if (scenario == "ota_ap_failure") {
    WiFi.ap_start_ok = false;
    started = board.startOTAUpdate("test", reply, true);
  } else if (scenario == "cleanup_none") {
    seedStation(); // An unowned driver is actually running before cleanup.
  } else if (scenario != "owners_none") {
    return 2;
  }

  if (scenario.compare(0, 8, "cleanup_") == 0) stopBridgeWiFiIfUnused();
  if (scenario == "ota_stale_ap") {
    // Inject raw-driver teardown, not OTA's recovery behavior. Wrapper caches
    // and the server pointer remain stale while the live AP/driver disappear.
    // The real startOTAUpdate() must either repair the AP or report failure.
    esp_wifi_stop();
    esp_wifi_deinit();
    assert(!sdk_initialized && !sdk_started && !sdk_ap_active);
    assert(WiFi.initialized_cache && WiFi.started_cache && board.isOTAUpdateRunning());
    started = board.startOTAUpdate("test", reply, true);
  } else if (scenario == "ota_ap_repeat" || scenario == "ota_sta_repeat") {
    started = board.startOTAUpdate("test", reply, false);
  }

  std::cout << "{\"scenario\":\"" << scenario << "\",\"enabled\":" << unsigned(backend.enabled())
      << ",\"stop_calls\":" << wifi_stop_calls << ",\"deinit_calls\":" << wifi_deinit_calls
      << ",\"first_started\":" << first_started << ",\"started\":" << started
      << ",\"zero_url\":" << (std::strstr(reply, "Started: http://0.0.0.0/") != nullptr)
      << ",\"zero_ip\":" << ((WiFi.status() == WL_CONNECTED ? WiFi.localIP() : WiFi.softAPIP()).value == 0)
      << ",\"endpoint_usable\":" << endpointUsable()
      << ",\"sdk_initialized\":" << sdk_initialized << ",\"sdk_started\":" << sdk_started
      << ",\"sdk_ap_active\":" << sdk_ap_active
      << ",\"initialized_cache\":" << WiFi.initialized_cache << ",\"started_cache\":" << WiFi.started_cache
      << ",\"station_ip\":\"" << WiFi.station_ip.toString() << "\",\"ap_ip\":\"" << WiFi.ap_ip.toString() << "\""
      << ",\"reply\":\"" << reply << "\",\"server_count\":" << server_count
      << ",\"server_begin_calls\":" << server_begin_calls << ",\"ap_start_calls\":" << WiFi.ap_start_calls
      << ",\"ota_running\":" << board.isOTAUpdateRunning()
      << ",\"sleep_inhibited\":" << board.inhibit_sleep << "}\n";
}
'''


def production_harness():
    """Extract real bodies, explicitly selecting ElegantOTA, not LightweightOTA."""
    infrastructure = (ROOT / "examples/InfrastructureWireless.h").read_text()
    bridge = (ROOT / "src/helpers/bridges/ESPNowBridge.cpp").read_text()
    board_source = (ROOT / "src/helpers/ESP32Board.cpp").read_text()
    board_header = (ROOT / "src/helpers/ESP32Board.h").read_text()
    elegant = board_source.index(
        "#elif defined(ADMIN_PASSWORD) && !defined(DISABLE_WIFI_OTA)")
    start_ota = method(board_source[elegant:], "bool ESP32Board::startOTAUpdate(")
    enabled = method(infrastructure, "uint8_t enabled() const override")
    cleanup = method(bridge, "static void stopBridgeWiFiIfUnused(")
    ota_running = method(board_header, "bool isOTAUpdateRunning() const override")
    return (STUBS.replace("@ENABLED@", enabled).replace("@CLEANUP@", cleanup)
            .replace("@START_OTA@", start_ota)
            .replace("@OTA_RUNNING@", ota_running.replace(" override", "")) + CHECKS)


class WifiOtaLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="meshcore-wifi-ota-")
        cls.addClassCleanup(directory.cleanup)
        folder = Path(directory.name)
        source = folder / "lifecycle.cpp"
        binary = folder / ("lifecycle.exe" if os.name == "nt" else "lifecycle")
        source.write_text(production_harness())
        subprocess.run([
            os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "src"), str(source), "-o", str(binary),
        ], check=True, capture_output=True, text=True, timeout=60)
        cls.observations = {}
        for scenario in SCENARIOS:
            result = subprocess.run([str(binary), scenario], check=True,
                                    capture_output=True, text=True, timeout=10)
            observation = json.loads(result.stdout)
            if observation["scenario"] != scenario:
                raise ValueError(f"Wrong scenario from fixture: {observation!r}")
            # Missing/malformed metrics must not become an expected assertion
            # failure merely because only a known-bug test consumes that field.
            numeric_fields = (
                "enabled", "stop_calls", "deinit_calls", "first_started", "started",
                "zero_url", "zero_ip", "server_count", "server_begin_calls",
                "ap_start_calls", "ota_running", "sleep_inhibited",
                "endpoint_usable", "sdk_initialized", "sdk_started", "sdk_ap_active",
                "initialized_cache", "started_cache",
            )
            if (any(type(observation.get(field)) is not int for field in numeric_fields)
                    or any(type(observation.get(field)) is not str
                           for field in ("reply", "station_ip", "ap_ip"))):
                raise ValueError(f"Malformed fixture metrics: {observation!r}")
            cls.observations[scenario] = observation

    def test_no_service_has_no_wifi_owner(self):
        self.assertEqual(self.observations["owners_none"]["enabled"], 0)

    def test_webconfig_owns_wifi(self):
        self.assertEqual(self.observations["owners_web"]["enabled"], 1)

    def test_mqtt_owns_wifi(self):
        self.assertEqual(self.observations["owners_mqtt"]["enabled"], 1)

    def test_espnow_alone_is_not_infrastructure_wifi(self):
        self.assertEqual(self.observations["owners_espnow"]["enabled"], 4)

    @unittest.expectedFailure
    def test_http_ota_alone_owns_wifi(self):
        """Known bug: enabled() omits board HTTP OTA ownership in both AP and STA modes."""
        self.assertEqual(tuple(self.observations[scenario]["enabled"] & 1
                               for scenario in ("owners_httpota", "owners_httpota_sta")), (1, 1))

    def assert_cleanup(self, scenario, count):
        observation = self.observations[scenario]
        self.assertEqual(observation["stop_calls"], count)
        self.assertEqual(observation["deinit_calls"], count)
        self.assertEqual(observation["sdk_initialized"], 1 - count)
        self.assertEqual(observation["sdk_started"], 1 - count)
        self.assertTrue(observation["initialized_cache"] and observation["started_cache"])
        self.assertEqual(observation["endpoint_usable"], 1 - count)
        if count == 0:
            if scenario == "cleanup_web":
                self.assertEqual(observation["ap_ip"], "192.168.4.1")
            else:
                self.assertEqual(observation["station_ip"], "10.0.0.7")

    def test_no_owner_stops_and_deinitializes_wifi(self):
        self.assert_cleanup("cleanup_none", 1)

    def test_webconfig_owner_protects_wifi_from_bridge_cleanup(self):
        self.assert_cleanup("cleanup_web", 0)

    def test_mqtt_owner_protects_wifi_from_bridge_cleanup(self):
        self.assert_cleanup("cleanup_mqtt", 0)

    def test_espnow_without_infrastructure_allows_driver_cleanup(self):
        self.assert_cleanup("cleanup_espnow", 1)

    @unittest.expectedFailure
    def test_http_ota_owner_protects_wifi_from_bridge_cleanup(self):
        """Known bug: raw cleanup stops/deinits the AP or STA owned only by HTTP OTA."""
        self.assertEqual(tuple((self.observations[scenario]["stop_calls"],
                                self.observations[scenario]["deinit_calls"],
                                self.observations[scenario]["endpoint_usable"],
                                self.observations[scenario]["station_ip" if scenario.endswith("_sta") else "ap_ip"])
                               for scenario in ("cleanup_httpota", "cleanup_httpota_sta")),
                         ((0, 0, 1, "192.168.4.1"), (0, 0, 1, "10.0.0.7")))

    def assert_healthy_ota(self, scenario, url, ap_starts):
        observation = self.observations[scenario]
        self.assertTrue(observation["first_started"] and observation["started"])
        self.assertEqual(observation["reply"], f"Started: http://{url}/update")
        self.assertEqual(observation["server_count"], 1)
        self.assertEqual(observation["server_begin_calls"], 1)
        self.assertEqual(observation["ap_start_calls"], ap_starts)
        self.assertTrue(observation["sdk_initialized"] and observation["sdk_started"]
                        and observation["endpoint_usable"])
        self.assertTrue(observation["ota_running"] and observation["sleep_inhibited"])

    def test_fresh_ap_ota_start(self):
        self.assert_healthy_ota("ota_ap_fresh", "192.168.4.1", 1)

    def test_healthy_ap_repeat_start_is_idempotent(self):
        self.assert_healthy_ota("ota_ap_repeat", "192.168.4.1", 1)

    def test_healthy_station_repeat_start_is_idempotent(self):
        self.assert_healthy_ota("ota_sta_repeat", "10.0.0.7", 0)

    @unittest.expectedFailure
    def test_stale_server_cannot_claim_success_at_zero_ap_ip(self):
        """Known bug: non-null ElegantOTA server bypasses dead-AP validation/recovery."""
        observation = self.observations["ota_stale_ap"]
        if observation["started"]:
            self.assertTrue(observation["endpoint_usable"])
            self.assertFalse(observation["zero_ip"] or observation["zero_url"])
            self.assertTrue(observation["reply"].startswith("Started: http://"))
        else:
            self.assertTrue(observation["reply"].startswith(("ERR", "Error")))
            self.assertFalse(observation["reply"].startswith("Started:"))

    def test_ap_start_failure_is_not_reported_as_success(self):
        observation = self.observations["ota_ap_failure"]
        self.assertFalse(observation["started"])
        self.assertEqual(observation["reply"], "ERR: OTA WiFi failed")
        self.assertEqual(observation["server_count"], 0)
        self.assertFalse(observation["ota_running"] or observation["sleep_inhibited"])


if os.environ.get("MESHCORE_REQUIRE_WIFI_OTA_FIX") == "1":
    # A strict run must fail on current firmware, and passes only after fixes.
    for test in vars(WifiOtaLifecycleTests).values():
        if getattr(test, "__unittest_expecting_failure__", False):
            test.__unittest_expecting_failure__ = False


if __name__ == "__main__":
    unittest.main()
