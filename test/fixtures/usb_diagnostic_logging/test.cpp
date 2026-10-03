#include <helpers/NonBlockingWriteStream.h>
#include <helpers/nrf52/EthernetCLI.h>
#include "NetworkLoggingMacro.h"

#include <iostream>

uint32_t mock_millis = 0;
RawSerial Serial;
MockFicr mock_ficr;
MockEthernet Ethernet;
std::string ethernet_output;
std::string ethernet_input;
bool accept_client = false;

class MockUsb : public Stream {
 public:
  int capacity = 256;
  bool refuse_write = false;
  unsigned int tries = 0;
  std::string output;
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override { assert(false && "blocking flush"); }
  int availableForWrite() override { return capacity; }
  size_t write(uint8_t) override { assert(false && "blocking write"); return 0; }
  size_t write(const uint8_t*, size_t) override { assert(false && "blocking write"); return 0; }
};

static MockUsb usb;
static bool logging_enabled = true;
static size_t tryUsbWrite(void*, const uint8_t* data, size_t size) {
  ++usb.tries;
  if (usb.refuse_write || usb.capacity <= 0) return 0;
  const size_t written = size < static_cast<size_t>(usb.capacity)
      ? size : static_cast<size_t>(usb.capacity);
  usb.output.append(reinterpret_cast<const char*>(data), written);
  return written;
}
static mesh::SingleAttemptNonBlockingStream logging_port(usb, tryUsbWrite);
namespace mesh {
bool isUsbLoggingEnabled() { return logging_enabled; }
Stream& usbLoggingPort() { return logging_port; }
}

static void reset() {
  usb.output.clear();
  usb.capacity = 256;
  usb.refuse_write = false;
  usb.tries = 0;
  logging_enabled = true;
  ethernet_running = false;
  ethernet_client = EthernetClient();
  ethernet_output.clear();
  ethernet_input.clear();
  accept_client = false;
  Ethernet = MockEthernet();
  mock_millis = 0;
}

static void acceptClientAndReply() {
  accept_client = true;
  ethernet_loop_maintain();
  assert(ethernet_take_session_reset());
  assert(!ethernet_take_session_reset());
  ethernet_input = "eth.status\r";
  char command[80] = {};
  assert(ethernet_read_line(command, sizeof(command)));
  assert(strcmp(command, "eth.status") == 0);
  char reply[80] = {};
  assert(ethernet_handle_command(command, reply));
  ethernet_send_reply(reply);
  assert(ethernet_output == "MeshCore CLI\r\n\r\n  -> ETH: 192.168.1.42:23\r\n");
}

int main() {
  (void)&ethernet_start_task;
  // Runtime-off diagnostics must not attempt USB, while functional Ethernet
  // commands and the client banner still work.
  reset();
  logging_enabled = false;
  ethernet_task(nullptr);
  acceptClientAndReply();
  assert(usb.output.empty() && usb.tries == 0 && mock_millis == 0);

  reset();
  ethernet_task(nullptr);
  acceptClientAndReply();
  assert(usb.output.find("ETH: MAC: 02:92:1F:12:34:56\n") != std::string::npos);
  assert(usb.output.find("ETH: Listening on TCP port 23\n") != std::string::npos);
  assert(usb.output.find("ETH: Client connected from 192.168.1.42\n") != std::string::npos);
  assert(usb.tries == 6 && mock_millis == 0);

  // An open-but-stalled host has no TX space. No raw write or wait is allowed.
  reset();
  usb.capacity = 0;
  ethernet_task(nullptr);
  acceptClientAndReply();
  assert(usb.output.empty() && usb.tries == 0 && mock_millis == 0);

  // The host can also vanish after the capacity preflight. The real shared
  // single-attempt facade drops each diagnostic instead of retrying or waiting.
  reset();
  usb.refuse_write = true;
  ethernet_task(nullptr);
  acceptClientAndReply();
  assert(usb.output.empty() && usb.tries == 6 && mock_millis == 0);

  for (int failure : {0, 1, 2}) {
    reset();
    Ethernet.failures = 1;
    if (failure == 0) Ethernet.hardware = EthernetNoHardware;
    if (failure == 1) Ethernet.link = LinkOFF;
    ethernet_task(nullptr);
    const char* expected = failure == 0 ? "Hardware not found, giving up"
        : failure == 1 ? "Cable not connected, will retry" : "DHCP failed, will retry";
    assert(usb.output.find(expected) != std::string::npos);
    assert(mock_millis == (failure == 0 ? 0u : 30000u));
  }

  reset();
  int evaluated = 0;
  logging_enabled = false;
  NETWORK_DEBUG_PRINTLN("suppressed %d", ++evaluated);
  assert(evaluated == 0 && usb.tries == 0);
  logging_enabled = true;
  usb.capacity = 0;
  NETWORK_DEBUG_PRINTLN("stalled %d", ++evaluated);
  assert(evaluated == 0 && usb.tries == 0);
  usb.capacity = 256;
  NETWORK_DEBUG_PRINTLN("visible %d", ++evaluated);
#if defined(MQTT_DEBUG) && MQTT_DEBUG
  assert(evaluated == 1 && usb.output == "MQTT: visible 1\n" && usb.tries == 1);
  usb.refuse_write = true;
  NETWORK_DEBUG_PRINTLN("disconnected %d", ++evaluated);
  assert(usb.tries == 2 && usb.output == "MQTT: visible 1\n");
#else
  assert(evaluated == 0 && usb.output.empty() && usb.tries == 0);
#endif
  assert(mock_millis == 0);
  std::cout << "PASS: gated USB diagnostics\n";
}
