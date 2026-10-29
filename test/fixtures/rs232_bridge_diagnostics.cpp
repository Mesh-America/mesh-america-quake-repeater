// Share hardware/pool/old-parser fixtures with the independent heartbeat suite.
// All diagnostics below exercise the compiled production RS232Bridge.cpp.
#define main heartbeat_fixture_main
#include "rs232_heartbeat/main.cpp"
#undef main

namespace diag = mesh::bridge::rs232diag;

std::vector<uint8_t> probe(uint32_t nonce) {
  std::vector<uint8_t> bytes(diag::FrameSize);
  bytes[0] = 0xC0; bytes[1] = 0x3E;
  assert(diag::encodeProbe(bytes.data() + 4, bytes.size() - 4, nonce));
  return bytes;
}

void probe_codec_test() {
  assert(diag::FrameSize == 52 && sizeof(diag::Stats) <= 128);
  for (uint32_t nonce : {0U, 1U, 0xA1B2C3D4U, UINT32_MAX}) {
    const auto frame = probe(nonce);
    assert(frame[2] == 0 && frame[3] == 0);
    assert(memcmp(frame.data() + 4, "DG1T", 4) == 0);
    for (size_t i = 4; i < frame.size(); ++i) assert(frame[i] < 0x80);
    uint32_t parsed = 0x12345678;
    assert(diag::decodeProbe(frame.data() + 4, 48, parsed) && parsed == nonce);
    hb::Control heartbeat;
    assert(!hb::decode(frame.data() + 4, heartbeat));
    for (size_t i = 4; i < frame.size(); ++i) for (unsigned bit = 0; bit < 8; ++bit) {
      auto bad = frame; bad[i] ^= 1U << bit;
      parsed = 0x12345678;
      assert(!diag::decodeProbe(bad.data() + 4, 48, parsed));
      assert(parsed == 0x12345678);
    }
    for (size_t size = 0; size < 80; ++size) if (size != 48) {
      parsed = 0x12345678;
      assert(!diag::decodeProbe(frame.data() + 4, size, parsed));
      assert(parsed == 0x12345678);
    }
  }
  std::array<uint8_t, 60> untouched; untouched.fill(0x55);
  assert(!diag::encodeProbe(untouched.data(), 47, 42));
  for (auto value : untouched) assert(value == 0x55);
  uint32_t nonce = 42;
  assert(!diag::encodeProbe(nullptr, 48, 1));
  assert(!diag::decodeProbe(nullptr, 48, nonce) && nonce == 42);
  auto reserved = probe(42); reserved[16] = '1'; rechecksum(reserved);
  assert(!diag::decodeProbe(reserved.data() + 4, 48, nonce));
}

void probe_isolation_test() {
  now_ms = 100; Peer sender(A_SESSION), receiver(B_SESSION);
  sender.driver.setHeartbeatEnabled(false);
  receiver.driver.setHeartbeatEnabled(false);
  sender.uart.delivered = [&](const uint8_t* data, size_t size) { receiver.uart.feed(data, size); };
  receiver.manager.starved = true;
  const auto last_peer = receiver.driver._power.peerAge(now_ms);
  assert(sender.driver.sendTest(0xA1B2C3D4));
  assert(sender.uart.tx.empty()); // Queueing is not serial or peer acceptance.
  sender.driver.loop(); receiver.driver.loop();
  assert(sender.uart.tx == probe(0xA1B2C3D4));
  assert(sender.driver._stats.probe.sent == 1);
  assert(receiver.driver._stats.probe.received == 1);
  assert(receiver.driver._stats.probe.last_rx_nonce == 0xA1B2C3D4);
  assert(sender.manager.allocations == 0 && receiver.manager.allocations == 0);
  assert(sender.manager.received.empty() && receiver.manager.received.empty());
  assert(sender.driver.seenCount() == 0 && receiver.driver.seenCount() == 0);
  assert(receiver.uart.tx.empty() && !receiver.driver._have_ack && !receiver.driver._legacy_rx);
  assert(receiver.driver._pong_target == 0 && !receiver.driver._power.hasPeer());
  assert(receiver.driver._power.peerAge(now_ms) == last_peer);
  receiver.driver.setHeartbeatEnabled(true);
  assert(receiver.driver.servicePowerPolicy(true, 1, now_ms + 1, true) == Action::Suspend);
  receiver.driver.setHeartbeatEnabled(false);
  for (unsigned i = 0; i < 5; ++i) { sender.driver.loop(); receiver.driver.loop(); }
  assert(sender.uart.tx.size() == diag::FrameSize && receiver.uart.tx.empty());
  auto bad = probe(42); bad[49] ^= 1;
  receiver.uart.feed(bad); receiver.driver.loop();
  assert(receiver.driver._stats.probe.bad == 1 && receiver.manager.allocations == 0);
  assert(receiver.driver._stats.probe.last_rx_nonce == 0xA1B2C3D4);
}

void probe_legacy_test() {
  for (unsigned parser = 0; parser < 2; ++parser) for (size_t prefix = 0; prefix <= diag::FrameSize; ++prefix) {
    NodePrefs prefs; HardwareSerial uart; uart.begin(115200);
    mesh::PacketManager manager;
    StockBridge old(&prefs, uart, &manager);
    UpstreamStockBridge upstream(&prefs, uart, &manager);
    BridgeBase* bridge = parser ? static_cast<BridgeBase*>(&upstream) : &old;
    const auto frame = probe(0xA1B2C3D4);
    uart.feed(frame.data(), prefix); bridge->loop();
    assert(manager.allocations == 0 && manager.received.empty());
    const auto data = data_frame({5, 6, 7, 8});
    uart.feed(data); bridge->loop();
    // A legacy parser cannot resynchronize a truncated header (1..3 bytes),
    // just as for any interrupted data frame. A whole probe or body prefix is
    // ignored and does not hide the following ordinary frame.
    if (prefix == 0 || prefix >= 6) {
      assert(manager.received == std::vector<std::vector<uint8_t>>({{5, 6, 7, 8}}));
      assert(manager.allocations == 1);
    }
  }
}

void probe_backpressure_test() {
  // All possible partial writes retain their exact prefix. A timeout cancels
  // only an unsent frame; a partial header keeps its unsent suffix owned until
  // UART recovery. This protects both legacy parsers from a later mesh header.
  for (size_t prefix = 0; prefix < diag::FrameSize; ++prefix) {
    now_ms = 100; Peer sender(A_SESSION), receiver(B_SESSION);
    sender.driver.setHeartbeatEnabled(false); receiver.driver.setHeartbeatEnabled(false);
    sender.uart.write_limit = prefix;
    assert(sender.driver.sendTest(0x12345678));
    sender.driver.drainTransmit(now_ms);
    assert(sender.uart.tx.size() == prefix);
    const auto accepted = sender.uart.tx;
    sender.uart.write_limit = 0;
    sender.driver.loop();
    assert(sender.uart.tx == accepted && sender.driver._stats.probe.sent == 0);
    now_ms += sender.driver.frameAssemblyMs();
    sender.driver.loop();
    assert(sender.driver._stats.probe.failed == 1);
    assert(sender.driver._tx_size == (prefix ? diag::FrameSize : 0));
    assert(sender.driver._stats.error == diag::Error::TestTimeout);
    if (prefix) assert(sender.driver._tx_wire_pending); // Prefix wire delay is not erased.
    for (unsigned n = 0; n < 3; ++n) sender.driver.loop();
    assert(sender.uart.tx == accepted && sender.driver._stats.probe.failed == 1);
    sender.uart.write_limit = SIZE_MAX;
    now_ms += 100;
    if (prefix) {
      assert(!sender.driver.sendTest(0xFEDCBA98));
      sender.driver.loop();
      assert(sender.uart.tx == probe(0x12345678));
      assert(sender.driver._stats.probe.sent == 1);
      now_ms += 100;
    }
    assert(sender.driver.sendTest(0xFEDCBA98)); sender.driver.loop();
    receiver.uart.feed(sender.uart.tx); receiver.driver.loop();
    assert(receiver.driver._stats.probe.received == (prefix ? 2U : 1U));
    assert(receiver.driver._stats.probe.last_rx_nonce == 0xFEDCBA98);
    for (unsigned parser = 0; parser < 2; ++parser) {
      NodePrefs prefs; HardwareSerial uart; uart.begin(115200);
      mesh::PacketManager manager;
      StockBridge old(&prefs, uart, &manager);
      UpstreamStockBridge upstream(&prefs, uart, &manager);
      BridgeBase* bridge = parser ? static_cast<BridgeBase*>(&upstream) : &old;
      uart.feed(sender.uart.tx); bridge->loop();
      assert(manager.allocations == 0);
      uart.feed(data_frame({5, 6, 7, 8})); bridge->loop();
      assert(manager.received == std::vector<std::vector<uint8_t>>({{5, 6, 7, 8}}));
    }
    assert(receiver.manager.allocations == 0 && !receiver.driver._power.hasPeer());
  }
  now_ms = 100; Peer completed(A_SESSION); completed.driver.setHeartbeatEnabled(false);
  completed.uart.write_limit = 1;
  assert(completed.driver.sendTest(0));
  for (unsigned i = 0; i < 26; ++i) completed.driver.loop();
  assert(completed.uart.tx == probe(0) && completed.driver._stats.probe.sent == 1);
  assert(completed.driver._stats.probe.failed == 0);
}

void probe_state_test() {
  now_ms = 100; Peer p(A_SESSION);
  const auto before = p.driver._power.peerAge(now_ms);
  assert(!p.driver.sendTest(1)); // Initial heartbeat must go first.
  assert(p.driver._stats.error == diag::Error::TestBusy && p.uart.tx.empty());
  p.driver.setHeartbeatEnabled(false);
  assert(p.driver.sendTest(2));
  assert(!p.driver.sendTest(3));
  assert(p.driver._stats.probe.last_tx_nonce == 2 && p.driver._power.peerAge(now_ms) == before);
  p.driver.end();
  assert(p.driver._stats.probe.failed == 3); // 2 rejected + 1 canceled.
  assert(!p.driver.sendTest(4));
  assert(p.driver._stats.error == diag::Error::TestStopped && !p.uart.installed);
  p.driver.begin();
  assert(p.driver._stats.probe.queued == 1 && p.driver._stats.probe.failed == 4);
  p.driver.setHeartbeatEnabled(true);
  p.enter_standby(now_ms + 1);
  assert(!p.driver.sendTest(5) && !p.uart.installed);
  assert(p.driver._power.suspended());
}

void diagnostic_counters_test() {
  now_ms = 100; Peer p(A_SESSION); p.driver.setHeartbeatEnabled(false);
  p.uart.feed({0x01, 0xC0, 0x11, 0xC0, 0x3E, 0xFF, 0xFF}); p.driver.loop();
  assert(p.driver._stats.rx.bytes == 7 && p.driver._stats.rx.noise == 2);
  assert(p.driver._stats.rx.length_bad == 1);
  auto bad = data_frame({4, 5, 6}); bad.back() ^= 1;
  p.uart.feed(bad); p.driver.loop();
  assert(p.driver._stats.rx.checksum_bad == 1 && p.driver._stats.rx.frames == 0);
  p.uart.feed({0xC0, 0x3E, 0, 10, 1}); p.driver.loop();
  now_ms += p.driver.frameAssemblyMs(); p.driver.loop();
  assert(p.driver._stats.rx.timeout == 1);
  p.manager.starved = true;
  p.uart.feed(data_frame({8, 9, 10})); p.driver.loop();
  for (unsigned n = 0; n < 10; ++n) p.driver.loop();
  assert(p.driver._stats.rx.frames == 1 && p.driver._stats.rx.pool_wait == 1);
  p.manager.starved = false; p.driver.loop();
  assert(p.driver._stats.rx.delivered == 1 && !p.driver._rx_packet_ready);
  mesh::Packet packet; packet.payload = {12, 13, 14};
  p.driver.sendPacket(&packet); p.driver.sendPacket(&packet);
  assert(p.driver._stats.tx.requested == 2 && p.driver._stats.tx.queued == 1);
  assert(p.driver._stats.tx.sent == 1 && p.driver._stats.tx.duplicate == 1);
  p.uart.feed(data_frame(packet.payload)); p.driver.loop();
  assert(p.driver._stats.rx.duplicate == 1 && p.driver._stats.rx.delivered == 1);
  packet.allowed = false; p.driver.sendPacket(&packet);
  assert(p.driver._stats.tx.filtered == 1);
  const auto old_rx = p.driver._stats.rx.bytes;
  p.driver.end(); p.driver.begin();
  assert(p.driver._stats.rx.bytes == old_rx && p.driver._stats.tx.sent == 1);
  p.driver._outstanding_challenge = 1234; p.driver._last_ack = 12;
  p.driver._pong_target = B_SESSION;
  p.uart.feed({0xC0}); p.driver.loop();
  const auto parser_pos = p.driver._rx_buffer_pos;
  p.driver.resetStats();
  assert(p.driver._stats.rx.bytes == 0 && p.driver._stats.tx.sent == 0);
  assert(p.driver._outstanding_challenge == 1234 && p.driver._last_ack == 12);
  assert(p.driver._rx_buffer_pos == parser_pos);
}

void diagnostic_bounds_test() {
  now_ms = 100; Peer p(A_SESSION); p.driver.setHeartbeatEnabled(false);
  for (uint32_t start : {0U, UINT32_MAX - 1, UINT32_MAX}) {
    uint32_t counter = start;
    diag::increment(counter);
    assert(counter == (start == UINT32_MAX ? UINT32_MAX : start + 1));
    diag::add(counter, SIZE_MAX); assert(counter == UINT32_MAX);
  }
  p.driver._stats.rx = {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
      UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX};
  p.driver._stats.tx = {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
      UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX};
  p.driver._stats.probe = {UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
      UINT32_MAX, UINT32_MAX, UINT32_MAX};
  for (const char* page : {"", "rx", "tx", "drops", "test", "invalid"}) {
    std::array<char, 200> output; output.fill('!');
    p.driver.formatStats(page, output.data(), 157);
    assert(strlen(output.data()) < 157 && output[157] == '!');
    if (strcmp(page, "drops") == 0) assert(strstr(output.data(), "big=4294967295"));
    p.driver.formatStats(page, output.data(), 1); assert(output[0] == 0);
    p.driver.formatStats(page, nullptr, 0);
  }
  p.prefs.bridge_baud = UINT32_MAX; p.driver._rx_pin = INT16_MIN; p.driver._tx_pin = INT16_MAX;
  p.driver._stats.error = diag::Error::TestStopped;
  char status[158]; memset(status, '!', sizeof(status));
  p.driver.formatStatus(status, 157);
  assert(strlen(status) < 157 && status[157] == '!');
  assert(strstr(status, "last=test.stopped"));
  p.driver.formatStatus(status, 1); assert(status[0] == 0);
  p.driver.formatStatus(nullptr, 0);
}

void diagnostic_debug_test() {
  now_ms = 1000; Peer p(A_SESSION); p.driver.setHeartbeatEnabled(false);
  mesh::logging_enabled = mesh::debug_enabled = false;
  p.driver.loop(); assert(mesh::debug_stream.writes == 0);
  mesh::debug_enabled = true; p.driver.loop(); assert(mesh::debug_stream.writes == 0);
  mesh::debug_enabled = false; mesh::logging_enabled = true;
  p.driver.loop(); assert(mesh::debug_stream.writes == 0);
  mesh::debug_enabled = true;
  p.driver.loop(); assert(mesh::debug_stream.writes == 1);
  const std::string text(mesh::debug_stream.bytes.begin(), mesh::debug_stream.bytes.end());
  assert(text.find("RS232: ready baud=115200 pins=5/6") != std::string::npos);
  assert(p.uart.tx.empty()); // Debug output never enters the bridge wire.
  now_ms += 10000; p.driver.loop(); assert(mesh::debug_stream.writes == 1);
  for (unsigned i = 0; i < 20; ++i) {
    p.uart.feed({1}); p.driver.loop();
  }
  assert(mesh::debug_stream.writes == 2); // At most one dirty summary/second.
  mesh::debug_stream.capacity = 0; now_ms += 1000;
  p.uart.feed({1}); p.driver.loop();
  const auto total = mesh::debug_stream.bytes.size();
  now_ms += 1000; p.uart.feed({1}); p.driver.loop();
  assert(mesh::debug_stream.bytes.size() == total);
  mesh::debug_stream.capacity = 4096;
  mesh::debug_enabled = false; now_ms += 1000; p.uart.feed({1}); p.driver.loop();
  assert(mesh::debug_stream.bytes.size() == total);
  mesh::debug_enabled = true; p.driver.loop();
  assert(mesh::debug_stream.bytes.size() > total && p.uart.tx.empty());
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string name = argv[1];
  if (name == "codec") probe_codec_test();
  else if (name == "isolation") probe_isolation_test();
  else if (name == "legacy") probe_legacy_test();
  else if (name == "backpressure") probe_backpressure_test();
  else if (name == "state") probe_state_test();
  else if (name == "counters") diagnostic_counters_test();
  else if (name == "bounds") diagnostic_bounds_test();
  else if (name == "debug") diagnostic_debug_test();
  else assert(false);
  printf("%s passed\n", name.c_str());
  return 0;
}
