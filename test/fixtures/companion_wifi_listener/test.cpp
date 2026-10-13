#include <helpers/wifi/SerialWifiInterface.h>
#include <helpers/MultiSerialInterface.h>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <vector>

uint32_t mock_millis = 100;
std::deque<WiFiClient> WiFiServer::incoming;

using Socket = std::shared_ptr<MockSocket>;
using Bytes = std::vector<uint8_t>;
static const IPAddress A(192, 168, 1, 20);
static const IPAddress B(192, 168, 1, 30);

struct Fixture {
  SerialWifiInterface transport;
  uint8_t input[MAX_FRAME_SIZE] = {};
  int cancellations = 0;
  Fixture() {
    transport.setSessionChangedCallback([](void* context) {
      ++static_cast<Fixture*>(context)->cancellations;
    }, this);
  }
  ~Fixture() { transport.end(); }
  bool start() { const bool result = transport.begin(5000); transport.enable(); return result; }
  size_t tick() { return transport.checkRecvFrame(input); }
  Socket connect(IPAddress ip, const Bytes& data = {}) {
    auto socket = std::make_shared<MockSocket>(ip);
    socket->received.insert(socket->received.end(), data.begin(), data.end());
    WiFiServer::incoming.push_back(WiFiClient(socket));
    tick();
    return socket;
  }
};

int main(int argc, char** argv) {
  assert(argc == 2);
  const int scenario = std::atoi(argv[1]);
  WiFiServer::resetDiagnostics();
  mock_millis = 100;
  Fixture f;
  if (scenario == 0) {
    WiFi.link_status = WL_DISCONNECTED;
    WiFi.station_ip = IPAddress();
    assert(!f.start());
    for (int i = 0; i < 100; ++i) { mock_millis += 1000; f.tick(); }
    auto status = f.transport.getStatus();
    assert(status.enabled && status.requested && !status.addressReady);
    assert(!status.listening && status.beginAttempts == 0 && status.beginFailures == 0);
    assert(WiFiServer::begin_calls == 0);
    WiFi.link_status = WL_CONNECTED;
    WiFi.station_ip = IPAddress(192, 168, 1, 10);
    f.tick();
    assert(f.transport.getStatus().listening && WiFiServer::begin_calls == 1);
  } else if (scenario == 1) {
    assert(f.start());
    const int ends = WiFiServer::end_calls;
    for (int i = 0; i < 100; ++i) { mock_millis += 1000; f.tick(); }
    assert(f.transport.begin(5000));
    assert(WiFiServer::begin_calls == 1 && WiFiServer::end_calls == ends);
    assert(WiFiServer::open_sockets == 1);
  } else if (scenario >= 2 && scenario <= 4) {
    WiFiServer::begin_fault = scenario == 2 ? WiFiServer::BeginFault::Socket
        : scenario == 3 ? WiFiServer::BeginFault::Bind : WiFiServer::BeginFault::Listen;
    assert(!f.start());
    auto failed = f.transport.getStatus();
    assert(!failed.listening && failed.beginAttempts == 1 && failed.beginFailures == 1);
    assert(!f.transport.isEnabled());
    assert(failed.retryInMs == 1000 && static_cast<int>(failed.lastStartError) != 0);
    assert(failed.lastErrno == (scenario == 2 ? ENOMEM : scenario == 3 ? EADDRINUSE : EIO));
    assert(WiFiServer::open_sockets == 0);
    for (int i = 0; i < 50; ++i) f.tick();
    assert(WiFiServer::begin_calls == 1 && WiFiServer::open_sockets == 0);
    mock_millis += 999; f.tick();
    assert(WiFiServer::begin_calls == 1);
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    ++mock_millis; f.tick();
    auto healed = f.transport.getStatus();
    assert(healed.listening && healed.beginAttempts == 2 && healed.beginFailures == 1);
    assert(healed.retryInMs == 0 && WiFiServer::open_sockets == 1);
    assert(healed.lastStartError == SerialWifiInterface::StartError::None && healed.lastErrno == 0);
    assert(f.transport.isEnabled());
  } else if (scenario == 5) {
    WiFiServer::begin_fault = WiFiServer::BeginFault::Listen;
    assert(!f.start());
    for (uint32_t delay : {1000U, 2000U, 4000U, 8000U, 16000U, 30000U, 30000U}) {
      auto before = f.transport.getStatus();
      assert(before.retryInMs == delay && WiFiServer::open_sockets == 0);
      mock_millis += delay - 1;
      for (int i = 0; i < 20; ++i) f.tick();
      assert(f.transport.getStatus().beginAttempts == before.beginAttempts);
      ++mock_millis; f.tick();
      assert(f.transport.getStatus().beginAttempts == before.beginAttempts + 1);
      assert(WiFiServer::open_sockets == 0);
    }
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    mock_millis += 30000; f.tick();
    assert(f.transport.getStatus().listening);
  } else if (scenario == 6) {
    mock_millis = UINT32_MAX - 500;
    WiFiServer::begin_fault = WiFiServer::BeginFault::Bind;
    assert(!f.start());
    mock_millis += 999; f.tick();
    assert(WiFiServer::begin_calls == 1 && f.transport.getStatus().retryInMs == 1);
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    ++mock_millis; f.tick();
    assert(f.transport.getStatus().listening && WiFiServer::begin_calls == 2);
  } else if (scenario == 7 || scenario == 8) {
    WiFiServer::begin_fault = WiFiServer::BeginFault::Bind;
    assert(!f.start());
    if (scenario == 7) f.transport.disable();
    else f.transport.end(); // The main loop uses end() for network suspension.
    assert(!f.transport.getStatus().requested && !f.transport.getStatus().listening);
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    mock_millis += 30000;
    f.transport.enable();
    for (int i = 0; i < 20; ++i) f.tick();
    assert(WiFiServer::begin_calls == 1 && WiFiServer::open_sockets == 0);
    assert(!f.transport.getStatus().requested);
    assert(f.transport.begin(5000));
    assert(f.transport.getStatus().listening);
  } else if (scenario == 9) {
    assert(f.start());
    auto socket = f.connect(A);
    const Bytes reply{0x01, 0x23, 0x45};
    assert(f.transport.writeFrame(reply.data(), reply.size()) == reply.size());
    WiFiServer::listener_lost = true;
    f.transport.loop();
    assert(f.transport.getStatus().listening);
    assert(f.transport.isConnected() && socket->connected && f.cancellations == 0);
    socket->write_limit = std::numeric_limits<size_t>::max();
    for (int i = 0; i < 5; ++i) f.tick();
    assert((socket->sent == Bytes{'>', 3, 0, 0x01, 0x23, 0x45}));
  } else if (scenario == 10) {
    assert(f.start());
    WiFi.link_status = WL_DISCONNECTED;
    WiFi.station_ip = IPAddress();
    f.tick();
    const int begins = WiFiServer::begin_calls;
    assert(f.transport.getStatus().requested && !f.transport.getStatus().addressReady);
    for (int i = 0; i < 20; ++i) { mock_millis += 1000; f.tick(); }
    assert(WiFiServer::begin_calls == begins);
    WiFi.link_status = WL_CONNECTED;
    WiFi.station_ip = IPAddress(192, 168, 1, 11);
    f.tick();
    assert(f.transport.getStatus().listening);
    auto socket = f.connect(A, Bytes{'<', 1, 0, 0x16});
    assert(socket->connected && f.input[0] == 0x16);
  } else if (scenario == 11) {
    WiFi.station_ip = IPAddress();
    assert(!f.start());
    f.tick();
    assert(!f.transport.getStatus().addressReady && WiFiServer::begin_calls == 0);
    WiFi.station_ip = IPAddress(192, 168, 1, 11);
    f.tick();
    assert(f.transport.getStatus().listening);
  } else if (scenario == 12 || scenario == 13) {
    WiFi.link_status = WL_DISCONNECTED;
    WiFi.station_ip = IPAddress();
    WiFi.mode_value = WIFI_AP;
    if (scenario == 12) WiFi.access_point_ip = IPAddress(192, 168, 4, 1);
    assert(f.start() == (scenario == 12));
    f.tick();
    assert(f.transport.getStatus().addressReady == (scenario == 12));
    assert(f.transport.getStatus().listening == (scenario == 12));
    assert(WiFiServer::begin_calls == (scenario == 12 ? 1 : 0));
  } else if (scenario == 14) {
    assert(f.start());
    auto old = f.connect(A, Bytes{'<', 1, 0, 0x11});
    auto next = f.connect(B, Bytes{'<', 1, 0, 0x12});
    assert(!old->connected && next->connected && f.cancellations == 1);
    auto status = f.transport.getStatus();
    assert(status.acceptedClients == 2 && status.validFrames == 2);
    assert(status.lastOpcode == 0x12 && status.clientConnected && status.listening);
    assert(status.disconnects == 1);
    assert(status.lastDisconnectReason == SerialWifiInterface::DisconnectReason::Replaced);
  } else if (scenario == 15) {
    assert(f.start());
    auto socket = f.connect(A);
    auto accepted = f.transport.getStatus();
    assert(accepted.acceptedClients == 1 && accepted.validFrames == 0);
    socket->received = {'<', 1, 0, 0x16};
    assert(f.tick() == 1);
    auto parsed = f.transport.getStatus();
    assert(parsed.validFrames == 1 && parsed.lastOpcode == 0x16);
    socket->received = {'<', 2, 0, 0x42, 0x17};
    assert(f.tick() == 2);
    assert(f.transport.getStatus().validFrames == 2);
    assert(f.transport.getStatus().lastOpcode == 0x42);
    socket->connected = false; f.tick(); f.tick();
    assert(f.transport.getStatus().disconnects == 1);
    assert(f.transport.getStatus().lastDisconnectReason == SerialWifiInterface::DisconnectReason::PeerClosed);
    assert(f.cancellations == 1 && !f.transport.getStatus().clientConnected);
  } else if (scenario == 16) {
    assert(f.start());
    auto socket = f.connect(A, Bytes{'?', 1, 0, '<', 1, 0, 0x16});
    auto status = f.transport.getStatus();
    assert(!socket->connected && !status.clientConnected);
    assert(status.acceptedClients == 1 && status.validFrames == 0 && status.disconnects == 1);
    assert(status.lastDisconnectReason == SerialWifiInterface::DisconnectReason::InvalidHeader);
    assert(socket->read_count == 3 && status.listening);
    for (int i = 0; i < 20; ++i) assert(f.tick() == 0);
    assert(f.transport.getStatus().disconnects == 1);
    f.connect(A, Bytes{'<', 1, 0, 0x16});
    assert(f.transport.getStatus().validFrames == 1);
  } else if (scenario == 17) {
    assert(f.start());
    auto socket = f.connect(A, Bytes{'<', 2, 0, 0x16});
    mock_millis += 4999; f.tick();
    assert(socket->connected && f.transport.getStatus().disconnects == 0);
    ++mock_millis; f.tick();
    auto status = f.transport.getStatus();
    assert(!socket->connected && status.disconnects == 1 && status.validFrames == 0);
    assert(status.lastDisconnectReason == SerialWifiInterface::DisconnectReason::FrameTimeout);
  } else if (scenario == 18) {
    assert(f.start());
    auto socket = f.connect(A);
    socket->received = {'<', 1, 0, 0x16};
    const int begins = WiFiServer::begin_calls, ends = WiFiServer::end_calls;
    for (int i = 0; i < 100; ++i) {
      auto status = f.transport.getStatus();
      assert(status.listening && status.validFrames == 0);
    }
    assert(socket->read_count == 0 && WiFiServer::begin_calls == begins && WiFiServer::end_calls == ends);
    assert(f.tick() == 1 && f.transport.getStatus().validFrames == 1);
  } else if (scenario == 19) {
    WiFiServer::begin_fault = WiFiServer::BeginFault::Listen;
    assert(!f.transport.begin(5000));
    assert(!f.transport.getStatus().enabled);
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    mock_millis += 30000;
    for (int i = 0; i < 20; ++i) f.tick();
    assert(WiFiServer::begin_calls == 1 && WiFiServer::open_sockets == 0);
    f.transport.enable(); f.tick();
    assert(f.transport.getStatus().listening && WiFiServer::begin_calls == 2);
  } else if (scenario == 20) {
    assert(f.start());
    auto socket = f.connect(A);
    const Bytes reply{0x05, 0x23, 0x45};
    assert(f.transport.writeFrame(reply.data(), reply.size()) == reply.size());
    assert(f.transport.getStatus().txFrames == 0);
    f.tick(); // A zero-byte write is neither a sent packet nor a failure.
    assert(f.transport.getStatus().txFrames == 0 && socket->sent.empty());
    socket->write_limit = 2;
    f.tick(); f.tick();
    assert(socket->sent.size() == 4 && f.transport.getStatus().txFrames == 0);
    f.tick();
    auto complete = f.transport.getStatus();
    assert(complete.txFrames == 1 && complete.lastTxOpcode == 0x05);
    for (int i = 0; i < 10; ++i) f.tick();
    assert(f.transport.getStatus().txFrames == 1);
  } else if (scenario == 21) {
    assert(!f.transport.begin(0));
    f.transport.enable();
    for (int i = 0; i < 20; ++i) { mock_millis += 1000; f.tick(); }
    auto status = f.transport.getStatus();
    assert(!status.requested && !status.listening && WiFiServer::begin_calls == 0);
    assert(status.beginAttempts == 0 && status.beginFailures == 0);
    assert(status.lastStartError == SerialWifiInterface::StartError::InvalidPort);
    assert(!f.transport.begin(65536));
    assert(f.transport.begin(5000));
    assert(f.transport.getStatus().listening);
  } else if (scenario == 22 || scenario == 23) {
    assert(f.start());
    auto socket = f.connect(A, scenario == 23 ? Bytes{'<', 2, 0} : Bytes{});
    socket->read_limit = 1;
    const Bytes remaining = scenario == 23 ? Bytes{0x16, 0x17} : Bytes{'<', 2, 0, 0x16, 0x17};
    socket->received.assign(remaining.begin(), remaining.end());
    assert(f.tick() == 0);
    auto status = f.transport.getStatus();
    assert(!socket->connected && status.validFrames == 0 && status.disconnects == 1);
    const auto expected = scenario == 22 ? SerialWifiInterface::DisconnectReason::ShortHeader
        : SerialWifiInterface::DisconnectReason::ShortPayload;
    assert(status.lastDisconnectReason == expected);
    assert(status.listening);
  } else if (scenario == 24) {
    assert(f.start());
    auto socket = f.connect(A, Bytes{'<', 1, 0, 0x16});
    const int begins = WiFiServer::begin_calls, ends = WiFiServer::end_calls;
    WiFi.station_ip = IPAddress(192, 168, 1, 99);
    f.tick();
    assert(f.transport.getStatus().listening && socket->connected && f.cancellations == 0);
    assert(WiFiServer::begin_calls == begins && WiFiServer::end_calls == ends);
  } else if (scenario == 25) {
    WiFiServer::begin_fault = WiFiServer::BeginFault::Socket;
    assert(!f.transport.begin(5000));
    MultiSerialInterface manager;
    assert(manager.addInterface(InterfaceType::WiFi, &f.transport));
    manager.enable();
    assert(!f.transport.isEnabled());
    assert(manager.checkRecvFrame(f.input) == 0);
    mock_millis += 1000;
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    manager.loop(); // Must service failed transports despite unavailable dispatch.
    assert(f.transport.isEnabled() && f.transport.getStatus().listening);
    auto socket = std::make_shared<MockSocket>(A);
    socket->received = {'<', 1, 0, 0x16};
    WiFiServer::incoming.push_back(WiFiClient(socket));
    assert(manager.checkRecvFrame(f.input) == 1 && f.input[0] == 0x16);
  } else if (scenario == 26) {
    assert(f.start());
    auto socket = f.connect(A);
    MultiSerialInterface manager;
    assert(manager.addInterface(InterfaceType::WiFi, &f.transport));
    manager.enable();
    socket->received = {'<', 1, 0, 0x04};
    assert(manager.checkRecvFrame(f.input) == 1 && f.input[0] == 0x04);
    manager.lockReplyRoute();
    assert(manager.isReplyRouteAvailable(&f.transport));
    const Bytes reply{0x05, 0x23, 0x45};
    assert(manager.writeFrame(reply.data(), reply.size()) == reply.size());
    WiFiServer::listener_lost = true;
    WiFiServer::begin_fault = WiFiServer::BeginFault::Bind;
    manager.loop();
    assert(!f.transport.getStatus().listening && socket->connected && f.cancellations == 0);
    assert(f.transport.hasPendingIO() && WiFiServer::open_sockets == 0);
    assert(f.transport.isEnabled() && manager.isConnected());
    assert(manager.isReplyRouteAvailable(&f.transport));
    // A separately accepted socket must continue this locked response stream
    // before listener repair succeeds; a listener-only readiness test breaks it.
    socket->write_limit = std::numeric_limits<size_t>::max();
    assert(manager.checkRecvFrame(f.input) == 0);
    assert((socket->sent == Bytes{'>', 3, 0, 0x05, 0x23, 0x45}));
    assert(f.transport.getStatus().txFrames == 1);
    socket->received = {'<', 1, 0, 0x16};
    assert(manager.checkRecvFrame(f.input) == 1 && f.input[0] == 0x16);
    assert(f.transport.getStatus().validFrames == 2);
    assert(!f.transport.getStatus().listening && WiFiServer::begin_calls == 2);
    mock_millis += 1000;
    WiFiServer::begin_fault = WiFiServer::BeginFault::None;
    manager.loop();
    assert(f.transport.getStatus().listening && socket->connected && f.cancellations == 0);
    assert(manager.isReplyRouteAvailable(&f.transport));
  } else if (scenario == 27) {
    WiFi.mode_value = WIFI_STA;
    WiFi.link_status = WL_DISCONNECTED;
    WiFi.station_ip = IPAddress();
    WiFi.access_point_ip = IPAddress(192, 168, 4, 1);
    assert(!f.start());
    f.tick();
    assert(!f.transport.getStatus().addressReady && WiFiServer::begin_calls == 0);
  } else {
    assert(false && "unknown scenario");
  }
  std::printf("PASS: Wi-Fi listener scenario %d\n", scenario);
}
