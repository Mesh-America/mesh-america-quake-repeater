#include <helpers/wifi/SerialWifiInterface.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <climits>

uint32_t mock_millis = 100;
std::deque<WiFiClient> WiFiServer::incoming;
constexpr int TCP_PORT = 5000;
constexpr int ESP_OK = 0;
struct wifi_ap_record_t {};
int esp_wifi_sta_get_ap_info(wifi_ap_record_t*) { return ESP_OK; }

struct DiagnosticInterface {
  SerialWifiInterface::Status snapshot{};
  int reads = 0;
  SerialWifiInterface::Status getStatus() { ++reads; return snapshot; }
} wifi_interface;
bool companion_wifi_interface_registered = true;
uint8_t companion_wifi_display_state = 3;
uint32_t companion_wifi_display_frames = 99;
bool companion_display_available = true;
uint8_t companion_display_begin_status = 0x3c;
bool companion_wifi_requested = true;
bool companion_wifi_active = true;

@METHODS@

int main() {
  using Transport = SerialWifiInterface;
  auto& status = wifi_interface.snapshot;
  status.state = Transport::State::Retrying;
  status.addressReady = true;
  status.port = 5000;
  status.beginFailures = 1;
  status.lastErrno = EADDRINUSE;
  status.retryInMs = 1;
  status.lastDisconnectReason = Transport::DisconnectReason::InvalidHeader;
  char reply[160] = {};
  formatCompanionWiFiTcpStatus(reply, sizeof(reply));
  assert(strstr(reply, "tcp=5000 retrying reg=1 ip=1 client=0 fail=1"));
  assert(strstr(reply, "retry=1s") && strstr(reply, "drop=invalid-header"));
  formatCompanionWiFiDisplayStatus(reply, sizeof(reply));
  assert(strstr(reply, "requested=1, services=1") && strstr(reply, "tcp=0"));
  status.listening = true;
  status.clientConnected = true;
  status.state = Transport::State::Listening;
  formatCompanionWiFiDisplayStatus(reply, sizeof(reply));
  assert(strstr(reply, "tcp=1"));
  formatCompanionWiFiTcpStatus(reply, sizeof(reply));
  assert(strstr(reply, "listening") && strstr(reply, "client=1"));

  // Full-width counters and errno must leave the final drop reason intact in
  // the actual 160-byte Companion command reply, not silently truncate it.
  status.state = Transport::State::WaitingIp;
  status.port = 65535;
  status.beginFailures = UINT32_MAX;
  status.acceptedClients = UINT32_MAX;
  status.validFrames = UINT32_MAX;
  status.txFrames = UINT32_MAX;
  status.lastOpcode = status.lastTxOpcode = 0xff;
  status.lastErrno = INT32_MIN;
  status.retryInMs = 30000;
  struct Guarded { char text[160]; char guard[8]; } guarded;
  memset(&guarded, 0x5a, sizeof(guarded));
  formatCompanionWiFiTcpStatus(guarded.text, sizeof(guarded.text));
  assert(strlen(guarded.text) < sizeof(guarded.text));
  assert(strstr(guarded.text, "fail=4294967295 err=-2147483648 retry=30s"));
  assert(strstr(guarded.text, "acc=4294967295 rx=4294967295/FF tx=4294967295/FF"));
  assert(strstr(guarded.text, "drop=invalid-header"));
  for (char byte : guarded.guard) assert(byte == 0x5a);
  // Correlated binary CLI replies reserve three of the 160 bytes for a tag.
  formatCompanionWiFiTcpStatus(guarded.text, 157);
  assert(strlen(guarded.text) < 157);
  assert(strstr(guarded.text, "drop=invalid-header"));
  for (char byte : guarded.guard) assert(byte == 0x5a);

  // Small/null buffers are normal API contracts, not a reason to touch the
  // transport. Status polling must not consume a command or open a client.
  const int reads = wifi_interface.reads;
  formatCompanionWiFiTcpStatus(nullptr, 160);
  formatCompanionWiFiTcpStatus(reply, 0);
  formatCompanionWiFiDisplayStatus(nullptr, 160);
  formatCompanionWiFiDisplayStatus(reply, 0);
  assert(wifi_interface.reads == reads);
  memset(&guarded, 0x5a, sizeof(guarded));
  formatCompanionWiFiTcpStatus(guarded.text, 1);
  assert(guarded.text[0] == 0 && guarded.text[1] == 0x5a);
  formatCompanionWiFiTcpStatus(guarded.text, 8);
  assert(guarded.text[7] == 0 && guarded.text[8] == 0x5a);
  companion_wifi_interface_registered = false;
  status.port = 0;
  formatCompanionWiFiTcpStatus(reply, sizeof(reply));
  assert(strstr(reply, "tcp=5000") && strstr(reply, "reg=0"));
  assert(WiFiServer::begin_calls == 0 && WiFiServer::incoming.empty());
  std::puts("PASS: production Wi-Fi diagnostic formatters");
}
