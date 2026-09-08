#pragma once

#include <Arduino.h>
#include <cstdarg>
#include <deque>
#include <functional>
#include <memory>
#include <string>
#include <vector>

enum wifi_mode_t { WIFI_OFF, WIFI_STA, WIFI_AP, WIFI_AP_STA };
constexpr int WL_CONNECTED = 3;
struct IPAddress {
  uint32_t value = 0;
  operator uint32_t() const { return value; }
  std::string toString() const { return "192.0.2.1"; }
};
struct MockWiFi {
  bool connected = false;
  wifi_mode_t mode = WIFI_OFF;
  IPAddress ap;
  int status() const { return connected ? WL_CONNECTED : 0; }
  wifi_mode_t getMode() const { return mode; }
  IPAddress softAPIP() const { return ap; }
};
inline MockWiFi WiFi;

struct MockTcpState {
  bool connected = true;
  bool no_delay = false;
  unsigned requests = 0, flushes = 0;
  std::deque<uint8_t> received;
  std::function<std::vector<uint8_t>(const uint8_t*, size_t)> respond;
};

class WiFiClient : public Stream {
public:
  std::shared_ptr<MockTcpState> state;
  WiFiClient() = default;
  explicit WiFiClient(std::shared_ptr<MockTcpState> s) : state(s) {}
  explicit operator bool() const { return state && state->connected; }
  bool connected() const { return bool(*this); }
  void stop() { if (state) state->connected = false; }
  void setNoDelay(bool on) { if (state) state->no_delay = on; }
  IPAddress remoteIP() const { return {1}; }
  int available() override { return state ? state->received.size() : 0; }
  int read() override {
    if (!available()) return -1;
    int byte = state->received.front();
    state->received.pop_front();
    return byte;
  }
  size_t write(const uint8_t* bytes, size_t length) override {
    if (!connected()) return 0;
    ++state->requests;
    const auto reply = state->respond(bytes, length);
    state->received.insert(state->received.end(), reply.begin(), reply.end());
    return length;
  }
  void flush() override {
    ++state->flushes;
    state->received.clear(); // Real WiFiClient flush discards received bytes.
  }
};

class WiFiServer {
public:
  inline static std::deque<WiFiClient> pending;
  explicit WiFiServer(uint16_t) {}
  void begin() {}
  void end() { pending.clear(); }
  WiFiClient available() {
    if (pending.empty()) return {};
    WiFiClient result = pending.front();
    pending.pop_front();
    return result;
  }
};

namespace mesh {
struct MockLog {
  std::string output;
  void println(const char* text) { output += text; output += '\n'; }
  void printf(const char* format, ...) {
    char line[256];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof line, format, args);
    va_end(args);
    output += line;
  }
};
inline MockLog& usbLoggingPort() { static MockLog log; return log; }
}
