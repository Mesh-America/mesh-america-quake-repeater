// WiFi and the HTTP server are peripheral fakes; both OTA lifecycle methods
// are inserted verbatim from ESP32Board.cpp by test_wifi_ota_start.py.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <helpers/WirelessControl.h>

#define MESH_DEBUG_PRINTLN(...) ((void)0)
constexpr int WL_CONNECTED = 3;
constexpr int HTTP_GET = 0;
constexpr int WIFI_AP = 2;
struct IPAddress {
  std::string value;
  IPAddress() = default;
  IPAddress(unsigned a, unsigned b, unsigned c, unsigned d) {
    value = std::to_string(a) + "." + std::to_string(b) + "."
        + std::to_string(c) + "." + std::to_string(d);
  }
  std::string toString() const { return value; }
  explicit operator uint32_t() const { return value.empty() || value == "0.0.0.0" ? 0 : 1; }
};
struct WiFiFake {
  bool connected = true, ap = false, allow_ap = true;
  unsigned starts = 0;
  int status() const { return connected ? WL_CONNECTED : 0; }
  int getMode() const { return ap ? WIFI_AP : 0; }
  IPAddress localIP() const { return IPAddress(10, 20, 30, 40); }
  IPAddress softAPIP() const { return ap ? IPAddress(192, 168, 4, 1) : IPAddress(0, 0, 0, 0); }
  bool softAPConfig(IPAddress ip, IPAddress gateway, IPAddress mask) {
    assert(ip.value == "192.168.4.1" && gateway.value == ip.value);
    assert(mask.value == "255.255.255.0");
    return allow_ap;
  }
  bool softAP(const char* ssid, const char* password) {
    assert(strcmp(ssid, "MeshCore-OTA") == 0 && password == nullptr);
    ++starts; ap = allow_ap; return ap;
  }
  void softAPdisconnect(bool) { ap = false; }
} WiFi;
static unsigned server_starts = 0;
struct AsyncWebServerRequest {
  void send(int, const char*, const char*) {}
  void send(int, const char*, const char*, const char*) {}
};
struct AsyncWebServer {
  explicit AsyncWebServer(int) {}
  template<class F> void on(const char*, int, F) {}
  void begin() { ++server_starts; }
  void end() {}
};
struct Elegant {
  void setID(const char*) {}
  void begin(AsyncWebServer*) {}
} AsyncElegantOTA;
static int SPIFFS;
struct ESP32Board {
  bool inhibit_sleep = false;
  bool ota_started_ap = false;
#ifdef LIGHTWEIGHT_WIFI_OTA
  void* ota_server = nullptr;
#else
  AsyncWebServer* ota_server = nullptr;
#endif
  const char* getManufacturerName() const { return "test"; }
  bool startOTAUpdate(const char*, char*, bool);
  bool stopOTAUpdate(char*);
};
struct LightweightServer {
  bool allow = true, running = false, allow_stop = true;
  bool begin(ESP32Board*) { ++server_starts; running = allow; return allow; }
  bool isRunning() const { return running; }
  bool end() { running = false; return allow_stop; }
} lightweight_ota_server;
#ifdef COMPANION_RADIO_FULL
static constexpr uint16_t LIGHTWEIGHT_OTA_PORT = 8080;
#else
static constexpr uint16_t LIGHTWEIGHT_OTA_PORT = 80;
#endif
struct esp_partition_t { unsigned address; };
static bool valid_partitions = true;
const esp_partition_t* esp_ota_get_running_partition() {
  static esp_partition_t value{0x10000}; return &value;
}
const esp_partition_t* esp_ota_get_next_update_partition(void*) {
  static esp_partition_t value{0x340000}; return valid_partitions ? &value : nullptr;
}
@METHODS@

int main() {
  ESP32Board board;
  struct { char text[160] = {}; uint32_t guard = 0x12345678; } reply;
  auto start = [&](bool ap, const char* ip, const char* instruction) {
    assert(board.startOTAUpdate("test node", reply.text, ap));
    assert(board.inhibit_sleep && board.ota_server);
    const std::string url = std::string("Started: http://") + ip
#ifdef COMPANION_RADIO_FULL
        + ":8080"
#endif
        + "/update";
    assert(strncmp(reply.text, url.c_str(), url.size()) == 0);
    assert(strstr(reply.text, instruction));
    assert(strlen(reply.text) < 160 && reply.guard == 0x12345678);
  };
  // Normal start reports the actual LAN address and does not disconnect it.
  start(false, "10.20.30.40", "same WiFi/LAN");
  assert(WiFi.connected && !WiFi.ap && WiFi.starts == 0 && server_starts == 1);
  start(false, "10.20.30.40", "same WiFi/LAN");
  assert(server_starts == 1);

  // A failed switch must leave the existing uploader protected from sleep.
  WiFi.allow_ap = false;
  assert(!board.startOTAUpdate("test node", reply.text, true));
  assert(strcmp(reply.text, "ERR: OTA WiFi failed") == 0);
  assert(board.inhibit_sleep && board.ota_server && WiFi.connected);
  WiFi.allow_ap = true;
  // In particular, an already-running LAN server must honor a later `ap`.
  start(true, "192.168.4.1", "Join WiFi MeshCore-OTA");
  assert(WiFi.ap && WiFi.connected && server_starts == 1);
  const auto ap_starts = WiFi.starts;
  start(true, "192.168.4.1", "Join WiFi MeshCore-OTA");
  assert(WiFi.starts == ap_starts); // Healthy repeats retain associated clients.
  WiFi.ap = false; // An external driver stop invalidates cached AP ownership.
  start(true, "192.168.4.1", "Join WiFi MeshCore-OTA");
  assert(WiFi.starts == ap_starts + 1);
#ifdef LIGHTWEIGHT_WIFI_OTA
  lightweight_ota_server.allow_stop = false;
  assert(!board.stopOTAUpdate(reply.text));
  assert(strstr(reply.text, "OTA stopping") && board.inhibit_sleep && board.ota_server);
  assert(!board.startOTAUpdate("test node", reply.text, true));
  assert(strstr(reply.text, "retry stop ota first"));
  lightweight_ota_server.allow_stop = true;
#endif
  assert(board.stopOTAUpdate(reply.text));
  assert(!board.inhibit_sleep && !board.ota_server && !WiFi.ap && WiFi.connected);

  WiFi.connected = false;
  start(false, "192.168.4.1", "Join WiFi MeshCore-OTA");
  assert(WiFi.ap && !WiFi.connected);
  assert(board.stopOTAUpdate(reply.text));
  WiFi.allow_ap = false;
  assert(!board.startOTAUpdate("test node", reply.text, false));
  assert(strcmp(reply.text, "ERR: OTA WiFi failed") == 0);
  assert(!board.inhibit_sleep && !board.ota_server);
  // A pending wireless shutdown must not race a newly started uploader.
  struct Backend : mesh::wireless::Backend {
    uint8_t active = mesh::wireless::All;
    uint8_t available() const override { return mesh::wireless::All; }
    uint8_t enabled() const override { return active; }
    uint8_t clients() const override { return 0; }
    mesh::wireless::Result set(uint8_t service, bool on) override {
      if (on) active |= service; else active &= ~service;
      return mesh::wireless::Result::Done;
    }
  } backend;
  auto& control = mesh::wireless::control();
  control.begin(backend);
  assert(control.handle("set 2.4ghz off", reply.text, 160, 100,
                        mesh::wireless::Independent));
  assert(!board.startOTAUpdate("test node", reply.text, false));
  assert(strstr(reply.text, "wireless change pending"));
  control.service(350);
  assert(control.masterOff() && control.blocked(mesh::wireless::WiFi));
  WiFi.allow_ap = true;
  start(false, "192.168.4.1", "Join WiFi MeshCore-OTA");
  assert(!control.masterOff() && !control.blocked(mesh::wireless::WiFi));
  assert(control.blocked(mesh::wireless::Bluetooth) && control.blocked(mesh::wireless::EspNow));
  assert(board.stopOTAUpdate(reply.text));
#ifdef LIGHTWEIGHT_WIFI_OTA
  WiFi.allow_ap = true;
  lightweight_ota_server.allow = false;
  assert(!board.startOTAUpdate("test node", reply.text, true));
  assert(strcmp(reply.text, "ERR: OTA server failed") == 0);
  assert(!board.inhibit_sleep && !board.ota_server && !WiFi.ap);
#ifdef COMPANION_RADIO_FULL
  valid_partitions = false;
  assert(!board.startOTAUpdate("test node", reply.text, false));
  assert(strstr(reply.text, "partition layout requires a USB firmware update"));
#endif
#endif
}
