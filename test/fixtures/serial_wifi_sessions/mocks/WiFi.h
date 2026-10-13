#pragma once

#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <memory>
#include <string>
#include <vector>

class IPAddress {
  uint32_t _address = 0;
public:
  IPAddress() = default;
  IPAddress(uint32_t address) : _address(address) {}
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d)
      : _address(uint32_t(a) << 24 | uint32_t(b) << 16 | uint32_t(c) << 8 | d) {}
  operator uint32_t() const { return _address; }
  bool operator==(const IPAddress& other) const { return _address == other._address; }
  bool operator!=(const IPAddress& other) const { return !(*this == other); }
  std::string toString() const {
    return std::to_string((_address >> 24) & 255) + "."
        + std::to_string((_address >> 16) & 255) + "."
        + std::to_string((_address >> 8) & 255) + "."
        + std::to_string(_address & 255);
  }
};

constexpr int WL_CONNECTED = 3;
constexpr int WL_DISCONNECTED = 6;
constexpr int WIFI_OFF = 0;
constexpr int WIFI_STA = 1;
constexpr int WIFI_AP = 2;
constexpr int WIFI_AP_STA = 3;

struct WiFiClass {
  int link_status = WL_CONNECTED;
  int mode_value = WIFI_STA;
  IPAddress station_ip{192, 168, 1, 10};
  IPAddress access_point_ip;
  int status() const { return link_status; }
  int getMode() const { return mode_value; }
  IPAddress localIP() const { return station_ip; }
  IPAddress softAPIP() const { return access_point_ip; }
};

inline WiFiClass WiFi;

struct MockSocket {
  IPAddress address;
  bool connected = true;
  size_t write_limit = 0;
  size_t read_limit = std::numeric_limits<size_t>::max();
  size_t read_count = 0;
  std::vector<uint8_t> sent;
  std::deque<uint8_t> received;
  explicit MockSocket(IPAddress value) : address(value) {}
};

class WiFiClient {
  std::shared_ptr<MockSocket> _socket;
public:
  WiFiClient() = default;
  explicit WiFiClient(std::shared_ptr<MockSocket> socket) : _socket(socket) {}
  explicit operator bool() { return _socket && _socket->connected; }
  // Match the pinned ESP32 SDK's non-const connected() signature. This catches
  // const transport accessors that accidentally rely on a const-only fake.
  bool connected() { return _socket && _socket->connected; }
  void stop() { if (_socket) _socket->connected = false; }
  IPAddress remoteIP() const { return _socket ? _socket->address : IPAddress(); }
  int available() { return connected() ? int(_socket->received.size()) : 0; }
  size_t read(uint8_t* dest, size_t size) {
    if (_socket) size = std::min(size, _socket->read_limit);
    size_t read = 0;
    while (connected() && read < size && !_socket->received.empty()) {
      dest[read++] = _socket->received.front();
      _socket->received.pop_front();
      ++_socket->read_count;
    }
    return read;
  }
  size_t readBytes(uint8_t* dest, size_t size) { return read(dest, size); }
  size_t write(const uint8_t* src, size_t size) {
    if (!connected()) return 0;
    const size_t written = std::min(size, _socket->write_limit);
    _socket->sent.insert(_socket->sent.end(), src, src + written);
    return written;
  }
};

class WiFiServer {
  bool _listening = false;
  bool _owns_socket = false;
public:
  enum class BeginFault { None, Socket, Bind, Listen };
  static std::deque<WiFiClient> incoming;
  inline static BeginFault begin_fault = BeginFault::None;
  inline static int begin_calls = 0;
  inline static int end_calls = 0;
  inline static int open_sockets = 0;
  inline static int last_port = 0;
  inline static bool listener_lost = false;
  static void resetDiagnostics() {
    begin_fault = BeginFault::None;
    begin_calls = end_calls = open_sockets = last_port = 0;
    listener_lost = false;
    incoming.clear();
    WiFi = WiFiClass{};
  }
  void begin(int port) {
    ++begin_calls;
    last_port = port;
    if (_listening) return;
    if (begin_fault == BeginFault::Socket) { errno = ENOMEM; return; }
    // The pinned Arduino ESP32 WiFiServer leaves its descriptor open when
    // bind/listen fails. A wrapper must call end() before a bounded retry.
    _owns_socket = true;
    ++open_sockets;
    if (begin_fault == BeginFault::Bind) { errno = EADDRINUSE; return; }
    if (begin_fault == BeginFault::Listen) { errno = EIO; return; }
    _listening = true;
    listener_lost = false;
    errno = 0;
  }
  void end() {
    ++end_calls;
    if (_owns_socket) --open_sockets;
    _owns_socket = _listening = false;
    listener_lost = false;
    incoming.clear();
    // Cleanup may overwrite errno; diagnostics must preserve the start error.
    errno = 0;
  }
  operator bool() { return _listening && !listener_lost; }
  WiFiClient available() {
    if (!static_cast<bool>(*this) || incoming.empty()) return WiFiClient();
    WiFiClient client = incoming.front();
    incoming.pop_front();
    return client;
  }
};
