#pragma once

#include <Arduino.h>
#include <SPI.h>

class IPAddress {
 public:
  uint8_t operator[](size_t index) const {
    static const uint8_t address[4] = {192, 168, 1, 42};
    return address[index];
  }
};

extern std::string ethernet_output;
extern std::string ethernet_input;
extern bool accept_client;
class EthernetClient {
  bool _connected = false;
 public:
  explicit EthernetClient(bool connected = false) : _connected(connected) {}
  explicit operator bool() const { return _connected; }
  bool connected() const { return _connected; }
  void stop() { _connected = false; }
  IPAddress remoteIP() const { return {}; }
  int available() const { return static_cast<int>(ethernet_input.size()); }
  int read() {
    assert(!ethernet_input.empty());
    const char value = ethernet_input.front();
    ethernet_input.erase(0, 1);
    return value;
  }
  void print(const char* text) { ethernet_output += text; }
  void println(const char* text = "") { ethernet_output += std::string(text) + "\r\n"; }
};

class EthernetServer {
 public:
  explicit EthernetServer(int) {}
  void begin() {}
  EthernetClient accept() {
    const bool accepted = accept_client;
    accept_client = false;
    return EthernetClient(accepted);
  }
};

enum { EthernetNoHardware = 0, EthernetPresent = 1, LinkOFF = 0, LinkON = 1 };
class MockEthernet {
 public:
  int failures = 0;
  int hardware = EthernetPresent;
  int link = LinkON;
  void init(SPIClass&, int) {}
  int begin(uint8_t*, int, int) {
    if (failures > 0) { --failures; return 0; }
    return 1;
  }
  int hardwareStatus() const { return hardware; }
  int linkStatus() const { return link; }
  IPAddress localIP() const { return {}; }
  void maintain() {}
};
extern MockEthernet Ethernet;
