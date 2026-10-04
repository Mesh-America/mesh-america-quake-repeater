#include <helpers/ArduinoSerialInterface.h>
#include <helpers/MultiSerialInterface.h>
#include <helpers/CompanionDelayedReplies.h>
#include <helpers/wifi/SerialWifiInterface.h>
#include <algorithm>
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <deque>
#include <limits>
#include <string>
#include <vector>

#include "production_constants.inc"
#include "production_stream.inc"

std::deque<WiFiClient> WiFiServer::incoming;
static bool usb_connected = true;
static bool usbConnected() { return usb_connected; }
static constexpr uint8_t ADV_TYPE_CHAT = 1;
struct ContactInfo { uint8_t type = ADV_TYPE_CHAT; };
struct Clock { unsigned long getMillis() const { return millis(); } };
struct Terminal {
  std::string text;
  void print(const char* value) { text += value; }
  void printf(const char* format, ...) {
    char buf[160];
    va_list args;
    va_start(args, format);
    vsnprintf(buf, sizeof(buf), format, args);
    va_end(args);
    text += buf;
  }
};

class MyMesh {
public:
  BaseSerialInterface* _serial = nullptr;
  Clock clock;
  Clock* _ms = &clock;
  uint8_t out_frame[MAX_FRAME_SIZE] = {};
#include "production_entry.inc"
  AckTableEntry expected_ack_table[EXPECTED_ACK_TABLE_SIZE] = {};
  int next_ack_idx = 0;
  bool has_next_ack_expiry = false;
  unsigned long next_ack_expiry = 0;
  unsigned cancelled = 0, one_key_notices = 0;
  mutable unsigned active_queries = 0;
  unsigned connection_ack_calls = 0;
  uint32_t connection_ack = 0, last_connection_ack = 0;
  ContactInfo* connection_ack_contact = nullptr;
  const uint8_t* last_connection_ack_input = nullptr;
  bool retry_active[256] = {};
  Terminal terminal;
  mesh::CompanionDelayedReplies _delayed_replies;
  BaseSerialInterface* command_radio_reply_route = nullptr;
  BaseSerialInterface* sign_data_reply_route = nullptr;
  BaseSerialInterface* private_key_backup_route = nullptr;
  unsigned long private_key_backup_deadline = 0;
  char private_key_backup_nonce[17] = {};
  uint8_t private_key_backup_sender[6] = {};
  bool command_radio_apply_pending = false;
  // Radio dispatch, peer-store, and terminal I/O are hardware boundaries. All
  // ACK state decisions and transport admission execute production code.
  bool cancelActiveRetries(const uint8_t* key) {
    ++cancelled;
    retry_active[key[0]] = false;
    return true;
  }
  bool hasActiveRetries(const uint8_t* key) const {
    ++active_queries;
    return retry_active[key[0]];
  }
  void rememberOneKeyAck(ContactInfo&) { ++one_key_notices; }
  bool checkConnectionsAck(const uint8_t* input, ContactInfo*& peer) {
    ++connection_ack_calls;
    last_connection_ack_input = input;
    memcpy(&last_connection_ack, input, sizeof(last_connection_ack));
    peer = last_connection_ack == connection_ack ? connection_ack_contact : nullptr;
    return peer != nullptr;
  }
  bool hasTerminalOutput() const { return true; }
  Terminal& terminalOutput() { return terminal; }
  void clearPendingReqs() { _delayed_replies.retireRequest(millis()); }
  void cancelPendingRadioParamApply() { command_radio_reply_route = nullptr; }
  void clearBinaryTraceReply() { _delayed_replies.retireBinaryTrace(millis()); }
  void cancelSigningSession() { sign_data_reply_route = nullptr; }
  bool millisHasNowPassed(unsigned long) const;
  unsigned long futureMillis(int) const;
  void clearExpectedAck(AckTableEntry&, bool = true);
  void expireExpectedAcks();
  AckTableEntry* findPendingTextMessage(const uint8_t*, uint32_t);
  bool processAck(const uint8_t*, ContactInfo*&);
  // Existing delivery scenarios inspect the optional peer; the lifetime suite
  // separately exercises ownership with a NULL peer through BaseChatMesh.
  ContactInfo* processAck(const uint8_t* input) {
    ContactInfo* peer = nullptr;
    processAck(input, peer);
    return peer;
  }
  void cancelSerialOperationsForRoute(BaseSerialInterface*);
  bool hasFiniteDelayedReplyForRoute(BaseSerialInterface*) const;
  void service();
  void remember(uint32_t, uint32_t, ContactInfo*, const uint8_t*, const uint8_t*, AckTableEntry* = nullptr);
};

#include "production_ack.inc"

using Bytes = std::vector<uint8_t>;
using Socket = std::shared_ptr<MockSocket>;
struct Fixture {
  BufferStream usb_stream, other_stream;
  ArduinoSerialInterface usb, other;
  SerialWifiInterface tcp;
  MultiSerialInterface manager;
  MyMesh mesh;
  ContactInfo recipient;
  uint8_t command[MAX_FRAME_SIZE] = {};

  Fixture() {
    g_mock_millis = 100;
    usb_connected = true;
    WiFiServer::incoming.clear();
    usb.begin(usb_stream); usb.enableFlowControl(true);
    usb.setConnectedCheck(usbConnected);
    other.begin(other_stream); other.enableFlowControl(true);
    tcp.begin(5000);
    assert(manager.addInterface(InterfaceType::USB, &usb));
    assert(manager.addInterface(InterfaceType::HardwareSerial, &other));
    assert(manager.addInterface(InterfaceType::WiFi, &tcp));
    manager.enable();
    mesh._serial = &manager;
    select(usb_stream, &usb);
  }
  ~Fixture() { tcp.end(); }

  void select(BufferStream& stream, BaseSerialInterface* target) {
    const uint8_t request[] = {'<', 1, 0, 1};
    stream.push(request, sizeof(request));
    assert(manager.checkRecvFrame(command) == 1);
    assert(manager.captureReplyRoute() == target);
  }
  Socket connect(IPAddress ip, size_t write_limit = 0) {
    auto socket = std::make_shared<MockSocket>(ip);
    socket->write_limit = write_limit;
    socket->received = {'<', 1, 0, 1};
    WiFiServer::incoming.push_back(WiFiClient(socket));
    size_t received = 0;
    for (int i = 0; i < 8 && received == 0; ++i) received = manager.checkRecvFrame(command);
    assert(received == 1);
    assert(manager.captureReplyRoute() == &tcp);
    return socket;
  }
  void queue(BaseSerialInterface* target, uint8_t code, unsigned count) {
    for (unsigned i = 0; i < count; ++i) {
      assert(manager.writeFrameToRoute(target, &code, 1) == 1);
    }
  }
  MyMesh::AckTableEntry& add(BaseSerialInterface* target = nullptr) {
    auto& entry = mesh.expected_ack_table[0];
    entry.ack = 0x11223344;
    entry.msg_sent = 50;
    entry.expires_at = 10000;
    entry.reply_route = target == nullptr ? &usb : target;
    entry.contact = &recipient;
    entry.message_timestamp = 1;
    entry.text_fingerprint[0] = 3;
    entry.retry_key[0] = 7;
    mesh.retry_active[7] = true;
    return entry;
  }
  ContactInfo* ack(uint32_t value = 0x11223344) {
    return mesh.processAck(reinterpret_cast<const uint8_t*>(&value));
  }
  void tick(uint32_t time) { g_mock_millis = time; mesh.service(); }
  void drain() {
    usb_stream.write_capacity = 4096;
    other_stream.write_capacity = 4096;
    for (int i = 0; i < 8; ++i) manager.loop();
  }
};

static std::vector<Bytes> frames(const Bytes& bytes) {
  std::vector<Bytes> result;
  size_t offset = 0;
  while (offset < bytes.size()) {
    assert(bytes.size() - offset >= 3 && bytes[offset] == '>');
    size_t size = bytes[offset + 1] | size_t(bytes[offset + 2]) << 8;
    offset += 3;
    assert(size <= bytes.size() - offset);
    result.emplace_back(bytes.begin() + offset, bytes.begin() + offset + size);
    offset += size;
  }
  return result;
}
static unsigned ackCount(const Bytes& bytes, uint32_t expected_rtt = 50) {
  unsigned count = 0;
  for (const auto& frame : frames(bytes)) {
    if (frame[0] != PUSH_CODE_SEND_CONFIRMED) continue;
    assert(frame.size() == 9);
    uint32_t ack, rtt;
    memcpy(&ack, frame.data() + 1, 4);
    memcpy(&rtt, frame.data() + 5, 4);
    assert(ack == 0x11223344 && rtt == expected_rtt);
    ++count;
  }
  return count;
}

int main() {
  unsigned checks = 0;
  {
    Fixture f;
    f.usb_stream.write_capacity = 0;
    f.queue(&f.usb, 0, 4);
    auto& entry = f.add();
    memset(f.mesh.out_frame, 0x5a, sizeof(f.mesh.out_frame));
    assert(f.ack() == &f.recipient);
    for (auto byte : f.mesh.out_frame) assert(byte == 0x5a);
    assert(entry.confirmed && entry.msg_sent == 50 && entry.expires_at == 10100);
    assert(f.mesh.cancelled == 1 && !f.mesh.retry_active[7]);
    assert(f.mesh.hasFiniteDelayedReplyForRoute(&f.usb));
    assert(f.mesh.next_ack_expiry == 110);
    f.drain();
    assert(ackCount(f.usb_stream.output) == 0);
    f.tick(109); assert(entry.ack != 0);
    f.tick(110); assert(entry.ack == 0);
    for (auto byte : f.mesh.out_frame) assert(byte == 0x5a);
    assert(!f.mesh.hasFiniteDelayedReplyForRoute(&f.usb));
    f.drain();
    assert(ackCount(f.usb_stream.output) == 1 && f.other_stream.output.empty());
    assert(f.mesh.cancelled == 1 && f.ack() == nullptr);
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0;
    f.queue(&f.usb, 0x80, 3); f.queue(&f.usb, 0, 1);
    auto& entry = f.add();
    assert(f.ack() == &f.recipient && entry.ack == 0);
    f.drain();
    assert(frames(f.usb_stream.output).size() == 4);
    assert(ackCount(f.usb_stream.output) == 1);
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add(); f.ack();
    const auto deadline = entry.expires_at;
    f.tick(2500); assert(f.ack() == nullptr);
    f.tick(9000); f.ack();
    assert(entry.expires_at == deadline && entry.msg_sent == 50 && f.mesh.cancelled == 1);
    assert(f.mesh.active_queries == 0);
    assert(f.mesh.one_key_notices == unsigned(MESH_ENABLE_ONE_KEY_DM));
    f.tick(10099); assert(entry.ack != 0 && f.mesh.next_ack_expiry == 10100);
    f.tick(10100); assert(entry.ack == 0 && !f.mesh.has_next_ack_expiry);
    assert(!f.mesh.hasFiniteDelayedReplyForRoute(&f.usb));
    assert(f.mesh.terminal.text.find("no ACK") == std::string::npos);
    f.drain(); assert(ackCount(f.usb_stream.output) == 0);
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add();
    g_mock_millis = UINT32_MAX - 4;
    entry.msg_sent = UINT32_MAX - 54; entry.expires_at = UINT32_MAX;
    f.ack(); assert(entry.msg_sent == 50 && entry.expires_at == 9995);
    assert(f.mesh.next_ack_expiry == 5);
    f.tick(4); assert(entry.ack != 0);
    f.tick(5); assert(entry.ack != 0);
    g_mock_millis = 30; f.ack(); assert(entry.msg_sent == 50);
    f.tick(9994); assert(entry.ack != 0);
    f.tick(9995); assert(entry.ack == 0);
    ++checks;
  }
  for (unsigned kind = 0; kind < 5; ++kind) {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add(); f.ack();
    if (kind == 0) usb_connected = false;
    if (kind == 1) f.usb.disable();
    if (kind == 2) assert(f.manager.removeInterface(&f.usb));
    if (kind == 3) f.manager.disable();
    if (kind == 4) { f.mesh.cancelSerialOperationsForRoute(&f.usb); f.usb.resetSessionState(); }
    f.tick(110);
    assert(entry.ack == 0 && f.mesh.cancelled == 1);
    assert(!f.mesh.hasFiniteDelayedReplyForRoute(&f.usb));
    assert(f.other_stream.output.empty());
    usb_connected = true; f.manager.enable(); f.drain();
    assert(ackCount(f.usb_stream.output) == 0);
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add();
    g_mock_millis = 25;
    entry.msg_sent = UINT32_MAX - 24;
    f.ack();
    assert(entry.msg_sent == 50 && entry.expires_at == 10025);
    f.drain(); f.tick(35); f.drain();
    assert(entry.ack == 0 && ackCount(f.usb_stream.output) == 1);
    ++checks;
  }
  {
    Fixture f;
    auto& entry = f.add();
    f.mesh.cancelSerialOperationsForRoute(&f.usb);
    assert(entry.ack != 0 && entry.reply_route == nullptr && f.mesh.retry_active[7]);
    assert(f.ack() == &f.recipient && entry.ack == 0 && f.mesh.cancelled == 1);
    assert(!f.mesh.retry_active[7] && f.usb_stream.output.empty());
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add(); f.ack();
    f.select(f.other_stream, &f.other);
    f.drain(); f.tick(110); f.drain();
    assert(entry.ack == 0 && ackCount(f.usb_stream.output) == 1);
    assert(f.other_stream.output.empty());
    ++checks;
  }
  {
    Fixture f;
    auto socket = f.connect(IPAddress(192, 168, 1, 2));
    f.queue(&f.tcp, 0, 4);
    auto& entry = f.add(&f.tcp); f.ack();
    assert(entry.confirmed && f.usb_stream.output.empty());
    socket->write_limit = 4096;
    for (int i = 0; i < 4; ++i) f.manager.checkRecvFrame(f.command);
    f.tick(110);
    for (int i = 0; i < 6; ++i) f.manager.checkRecvFrame(f.command);
    assert(entry.ack == 0 && ackCount(socket->sent) == 1 && f.usb_stream.output.empty());
    ++checks;
  }
  {
    Fixture f;
    auto socket = f.connect(IPAddress(192, 168, 1, 2));
    f.tcp.setSessionChangedCallback([](void* context) {
      auto& fixture = *static_cast<Fixture*>(context);
      fixture.mesh.cancelSerialOperationsForRoute(&fixture.tcp);
    }, &f);
    f.queue(&f.tcp, 0, 4);
    auto& entry = f.add(&f.tcp); f.ack();
    auto replacement = f.connect(IPAddress(192, 168, 1, 3));
    assert(entry.ack == 0 && f.mesh.cancelled == 1);
    replacement->write_limit = 4096;
    f.tick(110);
    for (int i = 0; i < 8; ++i) f.manager.checkRecvFrame(f.command);
    assert(ackCount(replacement->sent) == 0 && socket->sent.empty());
    assert(f.usb_stream.output.empty());
    // Do not let destructor callback outlive MyMesh (member destruction is reverse).
    f.tcp.setSessionChangedCallback(nullptr, nullptr);
    ++checks;
  }
  {
    Fixture f;
    auto socket = f.connect(IPAddress(192, 168, 1, 2));
    f.tcp.setSessionChangedCallback([](void* context) {
      auto& fixture = *static_cast<Fixture*>(context);
      fixture.mesh.cancelSerialOperationsForRoute(&fixture.tcp);
    }, &f);
    f.queue(&f.tcp, 0, 4);
    auto& entry = f.add(&f.tcp); f.ack();
    socket->connected = false;
    f.manager.loop();
    assert(entry.ack == 0 && f.mesh.cancelled == 1);
    assert(!f.mesh.hasFiniteDelayedReplyForRoute(&f.tcp));
    auto replacement = f.connect(IPAddress(192, 168, 1, 2), 4096);
    replacement->write_limit = 4096;
    for (int i = 0; i < 8; ++i) f.manager.checkRecvFrame(f.command);
    assert(ackCount(replacement->sent) == 0 && socket->sent.empty());
    assert(f.usb_stream.output.empty());
    f.tcp.setSessionChangedCallback(nullptr, nullptr);
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add();
    assert(f.mesh.findPendingTextMessage(entry.text_fingerprint, 2) == &entry);
    f.ack(); f.mesh.retry_active[7] = true; // a different lower-level retry must not revive this match
    const auto queries = f.mesh.active_queries;
    assert(f.mesh.findPendingTextMessage(entry.text_fingerprint, 2) == nullptr);
    assert(f.mesh.active_queries == queries);
    uint8_t fingerprint[MAX_HASH_SIZE] = {4}, key[MAX_HASH_SIZE] = {8};
    f.mesh.remember(0x55667788, 2, &f.recipient, fingerprint, key);
    assert(entry.ack == 0x55667788 && !entry.confirmed && entry.msg_sent == 100);
    assert(f.mesh.next_ack_idx == 1 && f.mesh.cancelled == 1);
    // Successful semantic replacement preserves the selected slot and resets
    // confirmed bookkeeping without changing the existing circular bound.
    f.mesh.remember(0x88776655, 3, &f.recipient, fingerprint, key, &entry);
    assert(entry.ack == 0x88776655 && f.mesh.next_ack_idx == 1);
    assert(f.mesh.cancelled == 1);
    ++checks;
  }
  {
    Fixture f;
    auto& entry = f.add(); entry.reply_route = nullptr;
#if COMPANION_FEATURE_TEXT_TERMINAL
    entry.terminal_origin = true;
#endif
    assert(f.ack() == &f.recipient && entry.ack == 0);
    assert(f.ack() == nullptr && f.mesh.cancelled == 1);
    assert(f.mesh.one_key_notices == unsigned(MESH_ENABLE_ONE_KEY_DM));
#if COMPANION_FEATURE_TEXT_TERMINAL
    assert(f.mesh.terminal.text == "\r\n  Got ACK! (round trip: 50 ms)\r\n> ");
#endif
    assert(f.usb_stream.output.empty());
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& first = f.add();
    auto& second = f.mesh.expected_ack_table[1];
    second = first;
    second.reply_route = &f.other;
    second.msg_sent = 75;
    second.retry_key[0] = 8;
    f.mesh.retry_active[8] = true;
    assert(f.ack() == &f.recipient && first.confirmed && !second.confirmed);
    assert(f.ack() == &f.recipient && first.confirmed && second.ack == 0);
    assert(f.mesh.connection_ack_calls == 0);
    assert(f.mesh.cancelled == 2 && !f.mesh.retry_active[7] && !f.mesh.retry_active[8]);
    f.drain();
    assert(ackCount(f.other_stream.output, 25) == 1);
    assert(f.ack() == nullptr && f.mesh.cancelled == 2);
    assert(f.mesh.connection_ack_calls == 1);
    f.tick(110); f.drain();
    assert(first.ack == 0 && ackCount(f.usb_stream.output) == 1);
    ++checks;
  }
  {
    Fixture f;
    auto& entry = f.add();
    ContactInfo connection;
    f.mesh.connection_ack = 0xdecafbad;
    f.mesh.connection_ack_contact = &connection;
    const uint32_t unmatched = f.mesh.connection_ack;
    const auto* input = reinterpret_cast<const uint8_t*>(&unmatched);
    assert(f.mesh.processAck(input) == &connection);
    assert(f.mesh.connection_ack_calls == 1);
    assert(f.mesh.last_connection_ack_input == input);
    assert(f.mesh.last_connection_ack == unmatched && unmatched == 0xdecafbad);
    assert(entry.ack == 0x11223344 && !entry.confirmed && f.mesh.retry_active[7]);
    assert(f.mesh.cancelled == 0 && f.mesh.one_key_notices == 0);
    assert(f.ack(0xaabbccdd) == nullptr && f.mesh.connection_ack_calls == 2);
    assert(f.mesh.last_connection_ack == 0xaabbccdd);
    assert(f.usb_stream.output.empty() && f.other_stream.output.empty());
    ++checks;
  }
  {
    Fixture f;
    f.usb_stream.write_capacity = 0; f.queue(&f.usb, 0, 4);
    auto& entry = f.add();
    ContactInfo connection;
    f.mesh.connection_ack = entry.ack;
    f.mesh.connection_ack_contact = &connection;
    // An unconfirmed chat match takes priority over the connection callback.
    assert(f.ack() == &f.recipient && entry.confirmed);
    assert(f.mesh.connection_ack_calls == 0 && f.mesh.cancelled == 1);
    const auto deadline = entry.expires_at;
    f.tick(2500);
    // A retained, already-confirmed duplicate may still be a connection ACK.
    assert(f.ack() == &connection && f.mesh.connection_ack_calls == 1);
    assert(entry.confirmed && entry.expires_at == deadline && entry.msg_sent == 50);
    assert(f.mesh.cancelled == 1);
    assert(f.mesh.one_key_notices == unsigned(MESH_ENABLE_ONE_KEY_DM));
    f.tick(10100);
    assert(entry.ack == 0);
    assert(f.ack() == &connection && f.mesh.connection_ack_calls == 2);
    f.drain(); assert(ackCount(f.usb_stream.output) == 0);
    ++checks;
  }
  {
    Fixture f;
    auto& entry = f.add();
    ContactInfo connection;
    f.mesh.connection_ack = entry.ack;
    f.mesh.connection_ack_contact = &connection;
    alignas(uint32_t) uint8_t bytes[sizeof(uint32_t) + 2] = {0xa5};
    uint8_t* input = bytes + 1;
    memcpy(input, &entry.ack, sizeof(entry.ack));
    bytes[sizeof(bytes) - 1] = 0x5a;
    uint8_t before[sizeof(bytes)];
    memcpy(before, bytes, sizeof(bytes));
    assert(reinterpret_cast<uintptr_t>(input) % alignof(uint32_t) != 0);
    assert(f.mesh.processAck(input) == &f.recipient && entry.ack == 0);
    assert(f.mesh.connection_ack_calls == 0 && f.mesh.cancelled == 1);
    assert(f.mesh.processAck(input) == &connection && f.mesh.connection_ack_calls == 1);
    assert(f.mesh.last_connection_ack_input == input && f.mesh.last_connection_ack == 0x11223344);
    assert(memcmp(bytes, before, sizeof(bytes)) == 0);
    assert(f.mesh.cancelled == 1);
    assert(f.mesh.one_key_notices == unsigned(MESH_ENABLE_ONE_KEY_DM));
    f.drain(); assert(ackCount(f.usb_stream.output) == 1);
    ++checks;
  }
  assert(checks == 21);
  printf("PASS: %u production ACK delivery checks\n", checks);
}
