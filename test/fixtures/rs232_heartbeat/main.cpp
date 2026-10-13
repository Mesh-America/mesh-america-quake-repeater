#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include <HardwareSerial.h>
#include <helpers/bridges/BridgeBase.h>

// Expose driver state only to assert adversarial/failure transitions. All
// behavior runs the compiled production .cpp, not a copied policy model.
#define private public
#include <helpers/bridges/RS232Bridge.h>
#undef private
#include "stock_parser.h"
#include "upstream_stock_parser.h"

uint32_t now_ms = 0;
uint32_t millis() { return now_ms; }
namespace hb = mesh::bridge::rs232heartbeat;
using Policy = mesh::bridge::RS232PowerPolicy;
using Action = RS232Bridge::PowerAction;
constexpr uint64_t A_SESSION = UINT64_C(0x1111222233334444);
constexpr uint64_t B_SESSION = UINT64_C(0xAAAABBBBCCCCDDDD);
constexpr uint64_t C_SESSION = UINT64_C(0x4321567812345678);

// Independent reference encoding catches field-offset/checksum changes. Wire
// data uses the pre-extension big-endian length + Fletcher16 specification.
uint16_t reference_checksum(const uint8_t* data, size_t size) {
  unsigned sum1 = 0, sum2 = 0;
  for (size_t i = 0; i < size; ++i) {
    sum1 = (sum1 + data[i]) % 255; sum2 = (sum2 + sum1) % 255;
  }
  return static_cast<uint16_t>((sum2 << 8) | sum1);
}
std::vector<uint8_t> data_frame(const std::vector<uint8_t>& bytes) {
  assert(!bytes.empty() && bytes.size() <= MAX_TRANS_UNIT + 1);
  std::vector<uint8_t> out{0xC0, 0x3E, static_cast<uint8_t>(bytes.size() >> 8),
                           static_cast<uint8_t>(bytes.size())};
  out.insert(out.end(), bytes.begin(), bytes.end());
  const auto checksum = reference_checksum(bytes.data(), bytes.size());
  out.push_back(static_cast<uint8_t>(checksum >> 8)); out.push_back(static_cast<uint8_t>(checksum));
  return out;
}
std::vector<uint8_t> control(char op, uint64_t sender, uint64_t target, uint32_t challenge) {
  char body[49]{};
  const int written = snprintf(body, sizeof(body), "HB1%c%016llX%016llX%08lX", op,
    static_cast<unsigned long long>(sender), static_cast<unsigned long long>(target),
    static_cast<unsigned long>(challenge));
  assert(written == 44);
  const auto checksum = reference_checksum(reinterpret_cast<uint8_t*>(body), 44);
  snprintf(body + 44, 5, "%04X", checksum);
  std::vector<uint8_t> out{0xC0, 0x3E, 0, 0};
  out.insert(out.end(), body, body + 48); return out;
}
void rechecksum(std::vector<uint8_t>& frame) {
  const auto sum = reference_checksum(frame.data() + 4, 44);
  char checksum[5]; snprintf(checksum, sizeof(checksum), "%04X", sum);
  std::copy(checksum, checksum + 4, frame.begin() + 48);
}

struct Peer {
  NodePrefs prefs;
  HardwareSerial uart;
  mesh::PacketManager manager;
  mesh::RTCClock rtc;
  RS232Bridge driver;
  bool enabled = true;
  unsigned resumes = 0, suspends = 0;
  explicit Peer(uint64_t session)
    : driver(&prefs, uart, 5, 6, &manager, &rtc) {
    driver.setHeartbeatSession(session); driver.begin(); assert(driver.isRunning());
  }
  void tick(bool allow = true, uint32_t idle = 300000, bool force = false) {
    if (!enabled) return; // Saved manual OFF is an owner gate, not standby.
    driver.loop();
    const auto action = driver.servicePowerPolicy(allow, idle, now_ms, force);
    if (action == Action::Suspend) {
      ++suspends; driver.end(); driver.completePowerAction(action, !driver.isRunning(), now_ms);
    } else if (action == Action::Resume) {
      ++resumes; driver.begin(); driver.completePowerAction(action, driver.isRunning(), now_ms);
    }
  }
  void enter_standby(uint32_t at, bool force = true) {
    now_ms = at;
    const auto action = driver.servicePowerPolicy(true, 0, now_ms, force);
    assert(action == Action::Suspend);
    driver.end(); driver.completePowerAction(action, true, now_ms);
    assert(driver.isPowerSuspended() && !uart.installed);
  }
  std::string status() const {
    char value[160]; driver.formatHeartbeatStatus(value, sizeof(value), now_ms); return value;
  }
  bool confirmed() const { return status().find("peer=confirmed") != std::string::npos; }
};

void codec_test() {
  assert(hb::FRAME_SIZE == 52 && hb::BODY_SIZE == 48);
  for (auto op : {'P', 'A'}) for (uint64_t sender : {A_SESSION, B_SESSION, UINT64_MAX}) {
    const uint64_t target = op == 'P' ? 0 : C_SESSION;
    const auto expected = control(op, sender, target, UINT32_MAX);
    std::array<uint8_t, 48> body{};
    hb::Control outgoing; outgoing.opcode = op; outgoing.sender = sender;
    outgoing.target = target; outgoing.challenge = UINT32_MAX;
    assert(hb::encode(body.data(), outgoing));
    assert(std::equal(body.begin(), body.end(), expected.begin() + 4));
    hb::Control parsed;
    assert(hb::decode(body.data(), parsed));
    assert(parsed.sender == sender && parsed.target == target && parsed.opcode == op
           && parsed.challenge == UINT32_MAX);
    for (const auto byte : body) assert(byte < 0x80); // Never embeds old magic C0 3E.
    for (size_t i = 0; i < body.size(); ++i) for (unsigned bit = 0; bit < 8; ++bit) {
      auto corrupted = body; corrupted[i] ^= 1U << bit;
      assert(!hb::decode(corrupted.data(), parsed));
    }
  }
  hb::Control parsed;
  for (const auto& bad : {
      control('X', A_SESSION, 0, 9), control('P', 0, 0, 9),
      control('P', A_SESSION, B_SESSION, 9), control('A', B_SESSION, 0, 9),
      control('P', A_SESSION, 0, 0)}) {
    assert(!hb::decode(bad.data() + 4, parsed));
  }
  for (const auto invalid : {
      hb::Control{0, 0, 9, 'P'}, hb::Control{A_SESSION, 0, 0, 'P'},
      hb::Control{A_SESSION, 0, 9, 'X'}, hb::Control{A_SESSION, B_SESSION, 9, 'P'},
      hb::Control{A_SESSION, 0, 9, 'A'}}) {
    std::array<uint8_t, 48> body; body.fill(0x55);
    assert(!hb::encode(body.data(), invalid));
    for (auto byte : body) assert(byte == 0x55);
  }
  auto version = control('P', A_SESSION, 0, 9); version[6] = '2'; rechecksum(version);
  assert(!hb::decode(version.data() + 4, parsed));
  auto lower = control('P', B_SESSION, 0, 9); lower[8] = 'a'; rechecksum(lower);
  assert(!hb::decode(lower.data() + 4, parsed));
  assert(!hb::encode(nullptr, parsed) && !hb::decode(nullptr, parsed));
}

void policy_test() {
  Policy p;
  assert(p.service(true, 300000, 0, true, false) == Action::None);
  assert(p.wakeDelay(0) == UINT32_MAX);
  assert(p.service(true, 300000, 299999, true, false) == Action::None);
  assert(p.service(true, 300000, 300000, true, true) == Action::None); // Complete RX/TX owns awake.
  assert(p.service(true, 300000, 300000, true, false) == Action::Suspend);
  assert(p.service(true, 300000, 300001, true, false) == Action::None); // Owner must complete.
  p.complete(Action::Resume, true, 300001); assert(!p.suspended()); // Wrong completion ignored.
  p.complete(Action::Suspend, false, 300001);
  assert(!p.suspended() && p.retrying());
  assert(p.wakeDelay(300001) == hb::ACTION_RETRY_MS);
  assert(p.service(true, 300000, 305000, true, false) == Action::None);
  assert(p.service(true, 300000, 305001, true, false) == Action::Suspend);
  p.complete(Action::Suspend, true, 305001);
  assert(p.suspended() && p.wakeDelay(305001) == 30000);
  assert(p.service(true, 300000, 335000, false, false) == Action::None);
  assert(p.service(true, 300000, 335001, false, false) == Action::Resume);
  p.complete(Action::Resume, false, 335001);
  assert(p.suspended() && p.retrying());
  assert(p.service(true, 300000, 340000, false, false) == Action::None);
  assert(p.service(true, 300000, 340001, false, false) == Action::Resume);
  p.complete(Action::Resume, true, 340001);
  assert(!p.suspended() && p.probing() && p.wakeDelay(340001) == 2000);
  p.notePeer(340002);
  assert(!p.probing() && p.hasPeer() && p.peerAge(340012) == 10);
  assert(p.service(true, 300000, 640001, true, false) == Action::None);

  Policy windows;
  windows.resetPeer(0);
  uint32_t t = 1;
  for (unsigned cycle = 1; cycle <= 16; ++cycle) {
    assert(windows.service(true, 1, t, true, false) == Action::Suspend);
    windows.complete(Action::Suspend, true, t);
    t += 30000;
    assert(windows.service(true, 1, t, false, false) == Action::Resume);
    windows.complete(Action::Resume, true, t);
    const uint32_t duration = cycle % 8 == 0 ? 40000 : 2000;
    assert(windows.probing() && windows.wakeDelay(t) == duration);
    t += duration;
  }
  // A long receive window contains a full peer short-cycle, plus an entire
  // heartbeat exchange allowance. This is the rendezvous guarantee, not RNG.
  static_assert(hb::LONG_PROBE_MS > hb::STANDBY_MS + hb::SHORT_PROBE_MS
    + hb::PROBE_PING_MS * 2, "long probe must cover a full unsynchronized cycle");

  Policy wrap;
  const uint32_t near_wrap = UINT32_MAX - 499;
  wrap.resetPeer(near_wrap);
  assert(wrap.service(true, 1000, near_wrap + 999, true, false) == Action::None);
  assert(wrap.service(true, 1000, near_wrap + 1000, true, false) == Action::Suspend);
  wrap.complete(Action::Suspend, true, near_wrap + 1000);
  assert(wrap.wakeDelay(near_wrap + 1001) == 29999);
  assert(wrap.service(true, 1000, near_wrap + 31000, false, false) == Action::Resume);
  wrap.complete(Action::Resume, true, near_wrap + 31000);
  assert(wrap.probing());
  assert(wrap.service(false, 1000, near_wrap + 33000, true, false) == Action::None);
  assert(!wrap.probing());
  for (uint32_t age = 0; age <= 500000; age += 1000)
    assert(wrap.service(false, 1, near_wrap + age, true, false) == Action::None);
}

void compatibility_test() {
  now_ms = 0;
  Peer default_peer(B_SESSION);
  for (now_ms = 0; now_ms < 400000; now_ms += 1000) default_peer.tick(true, 1000);
  assert(default_peer.uart.end_calls == 0 && !default_peer.uart.tx.empty());
  assert(!default_peer.driver._have_ack && !default_peer.driver.isPowerSuspended());
  assert(default_peer.status().find("armed=off") != std::string::npos);
  assert(default_peer.uart.tx.size() % hb::FRAME_SIZE == 0);
  for (size_t offset = 0; offset < default_peer.uart.tx.size(); offset += hb::FRAME_SIZE) {
    const auto* frame = default_peer.uart.tx.data() + offset;
    assert(frame[0] == 0xC0 && frame[1] == 0x3E && frame[2] == 0 && frame[3] == 0);
    hb::Control ping;
    assert(hb::decode(frame + 4, ping) && ping.opcode == 'P');
    assert(ping.sender == B_SESSION && ping.target == 0);
  }
  now_ms = 0;
  Peer peer(A_SESSION);
  peer.driver.setHeartbeatEnabled(false);
  // Disabling heartbeat restores a byte-for-byte legacy data-only stream.
  for (now_ms = 0; now_ms < 400000; now_ms += 1000) peer.tick(false);
  assert(peer.uart.tx.empty() && peer.uart.end_calls == 0);
  mesh::Packet data; data.payload = {0xC0, 0x3E, 0, 0, 255, 1, 2, 3};
  peer.driver.sendPacket(&data);
  assert(peer.uart.tx == data_frame(data.payload));
  const auto expected = peer.uart.tx;
  peer.driver.sendPacket(&data); assert(peer.uart.tx == expected); // Duplicate unchanged.

  for (unsigned version = 0; version < 2; ++version) {
    HardwareSerial uart; uart.begin(115200); NodePrefs prefs; mesh::PacketManager manager;
    StockBridge local(&prefs, uart, &manager);
    UpstreamStockBridge upstream(&prefs, uart, &manager);
    StockBridge& receiver = version == 0 ? local : upstream;
    // Both stock parser versions receive the exact production control bytes,
    // reject them without any Packet allocation and decode the next real data.
    uart.feed(default_peer.uart.tx); receiver.loop();
    while (uart.available()) receiver.loop();
    assert(manager.allocations == 0 && manager.received.empty());
    for (unsigned i = 1; i < 100; ++i) {
      uart.feed(control(i % 2 ? 'P' : 'A', B_SESSION, i % 2 ? 0 : A_SESSION, i));
      receiver.loop(); assert(manager.allocations == 0 && manager.received.empty());
    }
    uart.feed(expected); receiver.loop();
    assert(manager.allocations == 1 && manager.received.size() == 1
           && manager.received[0] == data.payload && uart.tx.empty());
  }
  // Real small UART FIFOs did not require a caller retry for legacy data. Keep
  // complete synchronous admission even when availableForWrite is just 64.
  Peer small_fifo(C_SESSION); small_fifo.driver.setHeartbeatEnabled(false);
  small_fifo.uart.tx_capacity = 64;
  mesh::Packet large1, large2;
  large1.payload.assign(MAX_TRANS_UNIT + 1, 0x11);
  large2.payload.assign(MAX_TRANS_UNIT + 1, 0x22);
  small_fifo.driver.sendPacket(&large1); small_fifo.driver.sendPacket(&large2);
  auto two_frames = data_frame(large1.payload);
  const auto second = data_frame(large2.payload); two_frames.insert(two_frames.end(), second.begin(), second.end());
  assert(small_fifo.uart.tx == two_frames && small_fifo.uart.write_calls == 2);
  // A prefilled remaining tail after a scheduling stall belongs to the
  // original stock frame. Timeout is for incomplete/noisy input, not for
  // throwing away valid bytes already in the UART driver.
  for (uint32_t pause : {500, 2000}) {
    now_ms = 0; Peer stalled(A_SESSION); stalled.driver.setHeartbeatEnabled(false);
    const auto full = data_frame(large1.payload);
    stalled.uart.feed(full.data(), 12); stalled.driver.loop();
    assert(stalled.driver._rx_buffer_pos == 12 && stalled.manager.received.empty());
    now_ms += pause; stalled.uart.feed(full.data() + 12, full.size() - 12);
    stalled.tick(true, 1000);
    assert(stalled.manager.received.size() == 1 && stalled.manager.received[0] == large1.payload);
    assert(!stalled.driver.isPowerSuspended()); // Legacy data never negotiates auto-standby.
  }
  // Stock TX -> new RX, including a maximum-length payload and a malformed
  // control interrupted by real legacy framing: no swallowing the data frame.
  std::vector<uint8_t> maximum(MAX_TRANS_UNIT + 1, 0xC0);
  maximum[1] = 0x3E;
  peer.uart.feed(data_frame(maximum)); peer.driver.loop();
  assert(peer.manager.received.back() == maximum);
  auto short_control = control('P', B_SESSION, 0, 42); short_control.resize(13);
  peer.uart.feed(short_control); peer.uart.feed(data_frame({10, 11, 12})); peer.driver.loop();
  assert(peer.manager.received.back() == std::vector<uint8_t>({10, 11, 12}));
  assert(peer.status().find("peer=legacy") != std::string::npos);
  assert(!peer.driver._have_ack); // Legacy traffic is not bidirectional proof.

  // A passive peer may respond to an opted-in neighbor without sending PING.
  const size_t before = peer.uart.tx.size();
  peer.uart.feed(control('P', B_SESSION, 0, 123)); peer.driver.loop();
  const auto ack = control('A', A_SESSION, B_SESSION, 123);
  assert(std::equal(ack.begin(), ack.end(), peer.uart.tx.begin() + before));
  assert(peer.uart.tx.size() == before + ack.size());
  assert(!peer.driver._have_ack);

  // Legacy inbound traffic can refresh its age but cannot negotiate a wake
  // schedule. Safe default autosleep still leaves that stock UART on forever.
  const auto ends = peer.uart.end_calls;
  now_ms += 500000; peer.tick(true, 1000);
  assert(peer.uart.end_calls == ends && peer.driver.isRunning()
         && !peer.driver._have_ack && !peer.driver.isPowerSuspended());

  Peer manual_off(C_SESSION); manual_off.driver.end(); manual_off.enabled = false;
  const unsigned starts = manual_off.uart.begin_calls;
  for (now_ms = 0; now_ms < 1000000; now_ms += 1000) manual_off.tick(true, 1);
  assert(!manual_off.driver.isRunning() && manual_off.uart.begin_calls == starts
         && manual_off.uart.tx.empty());
}

void peer_proof_test() {
  now_ms = 100;
  Peer peer(A_SESSION);
  peer.tick(true);
  peer.driver.loop();
  assert(peer.uart.tx == control('P', A_SESSION, 0, peer.driver._outstanding_challenge));
  const auto ping = peer.uart.tx;
  const uint32_t challenge = peer.driver._outstanding_challenge;
  assert(challenge != 0 && peer.manager.allocations == 0);
  peer.uart.feed(ping); peer.driver.loop();
  assert(!peer.driver._have_ack && peer.uart.tx == ping); // Physical TX reflection.
  for (const auto& bad : {
      control('A', B_SESSION, C_SESSION, challenge),
      control('A', B_SESSION, A_SESSION, challenge + 1),
      control('A', A_SESSION, A_SESSION, challenge),
      control('P', B_SESSION, 0, challenge)}) {
    peer.uart.feed(bad); peer.driver.loop(); assert(!peer.driver._have_ack);
  }
  auto bad_crc = control('A', B_SESSION, A_SESSION, challenge); bad_crc[51] ^= 1;
  peer.uart.feed(bad_crc); peer.driver.loop(); assert(!peer.driver._have_ack);
  auto version = control('A', B_SESSION, A_SESSION, challenge); version[6] = '2'; rechecksum(version);
  peer.uart.feed(version); peer.driver.loop(); assert(!peer.driver._have_ack);
  peer.uart.feed(std::vector<uint8_t>(700, 0x7F)); peer.driver.loop();
  assert(peer.uart.rx.size() == 188); peer.driver.loop(); // Bounded noisy RX work.
  const auto valid = control('A', B_SESSION, A_SESSION, challenge);
  now_ms += 1; peer.uart.feed(valid); peer.driver.loop();
  assert(peer.confirmed() && peer.driver._peer_session == B_SESSION);
  assert(peer.driver._outstanding_challenge == 0 && peer.manager.allocations == 0);
  const uint32_t last = peer.driver._last_ack;
  now_ms += 100; peer.uart.feed(valid); peer.driver.loop();
  assert(peer.driver._last_ack == last); // Consume ACK exactly once.
  char one[1]{'X'}; peer.driver.formatHeartbeatStatus(one, sizeof(one), now_ms); assert(one[0] == 0);
  peer.driver.formatHeartbeatStatus(nullptr, 1, now_ms);

  Peer self_echo(C_SESSION); self_echo.driver.setHeartbeatEnabled(false);
  mesh::Packet own; own.payload = {7, 3, 9}; self_echo.driver.sendPacket(&own);
  self_echo.uart.feed(self_echo.uart.tx); self_echo.driver.loop();
  assert(!self_echo.driver._have_ack && !self_echo.driver._legacy_rx
         && self_echo.manager.received.empty());

  // A new local session must invalidate ACKs for the old one, and a new remote
  // session is accepted only via a fresh current challenge response.
  peer.driver.setHeartbeatSession(C_SESSION);
  assert(!peer.driver._have_ack && peer.driver._peer_session == 0);
  peer.uart.feed(valid); peer.driver.loop(); assert(!peer.driver._have_ack);
  peer.tick(true); peer.driver.loop();
  const auto current = peer.driver._outstanding_challenge;
  assert(current != 0);
  now_ms += hb::ACK_MAX_AGE_MS + 1;
  peer.uart.feed(control('A', B_SESSION, C_SESSION, current)); peer.driver.loop();
  assert(!peer.driver._have_ack); // Correct fields but stale ACK.
  now_ms = UINT32_MAX - 25;
  peer.driver.setHeartbeatSession(UINT64_C(0x3333000011119999));
  peer.tick(true); peer.driver.loop(); const auto wrapping = peer.driver._outstanding_challenge;
  now_ms += 40;
  peer.uart.feed(control('A', B_SESSION, peer.driver._session, wrapping)); peer.driver.loop();
  assert(peer.confirmed());

  peer.driver.end(); peer.driver.begin();
  peer.driver._challenge_counter = UINT32_MAX;
  peer.driver.loop();
  assert(peer.driver._outstanding_challenge == 1); // Reserved zero is skipped.
  const auto previous = peer.driver._last_ack;
  now_ms += 10;
  peer.uart.feed(control('P', C_SESSION, 0, 55)); peer.driver.loop();
  assert(peer.driver._last_ack == previous); // Remote PING alone is not proof.
  peer.driver.setHeartbeatSession(0);
  const auto bytes_before = peer.uart.tx.size(); peer.driver.loop();
  assert(!peer.driver._have_ack && peer.uart.tx.size() == bytes_before);
}

void bounded_io_test() {
  now_ms = 0;
  Peer peer(A_SESSION);
  peer.uart.write_limit = 1;
  peer.tick(true); peer.driver.loop();
  assert(peer.driver._tx_size == hb::FRAME_SIZE && peer.driver._outstanding_challenge == 0);
  mesh::Packet packet; packet.payload = {9, 8, 7};
  peer.driver.sendPacket(&packet); // Does not interleave data into partial control.
  assert(peer.uart.tx.size() < hb::FRAME_SIZE);
  for (unsigned i = 0; i < 60; ++i) { ++now_ms; peer.driver.loop(); }
  const auto ping = control('P', A_SESSION, 0, peer.driver._outstanding_challenge);
  assert(peer.uart.tx == ping && peer.driver._outstanding_challenge != 0);
  peer.driver.sendPacket(&packet);
  for (unsigned i = 0; i < 12; ++i) { ++now_ms; peer.driver.loop(); }
  std::vector<uint8_t> expected = ping;
  const auto data = data_frame(packet.payload); expected.insert(expected.end(), data.begin(), data.end());
  assert(peer.uart.tx == expected && !peer.driver._have_ack);
  // Full TX admission is still not proof that an absent remote received it.
  assert(peer.driver._power.peerAge(now_ms) == UINT32_MAX);

  now_ms = 0; Peer blocked(B_SESSION); blocked.uart.write_limit = 0;
  blocked.tick(true, 1); blocked.driver.loop();
  now_ms = 1000;
  assert(blocked.driver.servicePowerPolicy(true, 1, now_ms, true) == Action::None);
  assert(blocked.uart.tx.empty() && blocked.driver._tx_size != 0);
  blocked.uart.write_limit = 4096; blocked.driver.loop();
  assert(blocked.driver._tx_size == 0);
  assert(blocked.driver.servicePowerPolicy(true, 1, now_ms, true) == Action::None); // Last bytes still on wire.
  now_ms += 100;
  assert(blocked.driver.servicePowerPolicy(true, 1, now_ms, true) == Action::Suspend);

  now_ms = 0; Peer starved(C_SESSION); starved.manager.starved = true;
  starved.uart.feed(data_frame({1, 3, 5})); starved.driver.loop();
  assert(starved.driver._rx_packet_ready && starved.manager.received.empty());
  now_ms = 1000;
  assert(starved.driver.servicePowerPolicy(true, 1, now_ms, true) == Action::None);
  starved.uart.feed(control('P', B_SESSION, 0, 7));
  const auto unread = starved.uart.rx.size(); starved.driver.loop();
  assert(starved.uart.rx.size() == unread && starved.driver._rx_packet_ready);
  starved.manager.starved = false; starved.driver.loop();
  assert(!starved.driver._rx_packet_ready && starved.manager.received.size() == 1);
  assert(starved.manager.received[0] == std::vector<uint8_t>({1, 3, 5}));
  assert(starved.uart.rx.empty()); // Control processing resumes after pool recovery.
  assert(starved.driver._power.peerAge(now_ms) == 1000); // Original arrival, not delayed allocation.

  now_ms = 0; Peer partial(A_SESSION);
  partial.uart.feed({0xC0, 0x3E, 0, 200, 1}); partial.driver.loop();
  assert(partial.driver._rx_buffer_pos == 5);
  const auto assembly = partial.driver.frameAssemblyMs();
  now_ms = assembly - 1; partial.uart.feed({2}); partial.driver.loop();
  assert(partial.driver._rx_buffer_pos == 6);
  now_ms = assembly; partial.driver.loop(); assert(partial.driver._rx_buffer_pos == 0);
  partial.uart.feed(data_frame({10, 20})); partial.driver.loop();
  assert(partial.manager.received.back() == std::vector<uint8_t>({10, 20}));

  // Repeated malformed frame starts do not restart the one deadline grace.
  now_ms = 0; Peer noise(C_SESSION);
  noise.driver.servicePowerPolicy(true, 100, now_ms, true);
  now_ms = 100; noise.uart.feed({0xC0, 0x3E, 0, 200}); noise.driver.loop();
  assert(noise.driver.servicePowerPolicy(true, 100, now_ms, true) == Action::None);
  const uint32_t deadline = noise.driver._partial_suspend_until;
  bool stopped = false;
  for (now_ms = 110; now_ms < deadline; now_ms += 10) {
    noise.uart.feed({0xC0, 0x3E, 0, 200}); noise.driver.loop();
    const auto action = noise.driver.servicePowerPolicy(true, 100, now_ms, true);
    assert(noise.driver._partial_suspend_until == deadline);
    if (action == Action::Suspend) {
      // A full malformed CRC frame can be discarded before the deadline.
      stopped = true; noise.driver.end(); noise.driver.completePowerAction(action, true, now_ms); break;
    }
    assert(action == Action::None);
  }
  if (!stopped) {
    now_ms = deadline;
    assert(noise.driver.servicePowerPolicy(true, 100, now_ms, true) == Action::Suspend);
  }

  now_ms = UINT32_MAX - 50; Peer wrapped_rx(A_SESSION);
  wrapped_rx.driver.setHeartbeatEnabled(false);
  wrapped_rx.uart.feed({0xC0, 0x3E, 0, 50}); wrapped_rx.driver.loop();
  const auto timeout = wrapped_rx.driver.frameAssemblyMs();
  now_ms += timeout; wrapped_rx.driver.loop();
  assert(wrapped_rx.driver._rx_buffer_pos == 0);
}

struct Pair {
  Peer a, b;
  bool cable = true;
  unsigned drop_controls = 0;
  uint32_t dropped_while_stopped = 0;
  Pair() : a(A_SESSION), b(B_SESSION) {
    a.uart.delivered = [&](const uint8_t* data, size_t size) { deliver(b, data, size); };
    b.uart.delivered = [&](const uint8_t* data, size_t size) { deliver(a, data, size); };
  }
  void deliver(Peer& peer, const uint8_t* data, size_t size) {
    if (!cable) return;
    if (drop_controls && size == hb::FRAME_SIZE) { --drop_controls; return; }
    if (!peer.uart.installed) { ++dropped_while_stopped; return; }
    peer.uart.feed(data, size);
  }
  void tick(uint32_t idle = 300000) {
    a.tick(true, idle); b.tick(true, idle);
    a.driver.loop(); b.driver.loop(); // bounded extra UART service, no forced wakes
  }
  bool confirmed() const { return a.confirmed() && b.confirmed(); }
  void negotiate() {
    // Learn the peer's capability through real challenge traffic, rather than
    // setting _have_ack in the fixture. This is the safe default sleep gate.
    const uint32_t start = now_ms;
    for (uint32_t elapsed = 0; elapsed < 1000 && !confirmed(); elapsed += 10) {
      now_ms = start + elapsed; tick();
    }
    assert(confirmed() && a.driver._have_ack && b.driver._have_ack);
  }
};

void rendezvous_test() {
  uint32_t max_recovery = 0;
  std::vector<uint32_t> phases{1, 1999, 2001, 29999, 30001, 31999};
  for (uint32_t phase = 0; phase < 32000; phase += 100) phases.push_back(phase);
  for (const auto phase : phases) {
    now_ms = 0; Pair pair;
    pair.negotiate();
    const uint32_t idle_at = now_ms + 300001;
    pair.a.enter_standby(idle_at, false); pair.b.enter_standby(idle_at + phase, false);
    assert(pair.a.driver._have_ack && pair.b.driver._have_ack); // Capability survives soft UART stop.
    const uint32_t start = idle_at + phase;
    bool recovered = false;
    for (uint32_t elapsed = 0; elapsed <= 328000; elapsed += 50) {
      now_ms = start + elapsed; pair.tick();
      if (pair.confirmed()) { max_recovery = std::max(max_recovery, elapsed); recovered = true; break; }
    }
    if (!recovered) fprintf(stderr, "No rendezvous at phase=%lu\n", static_cast<unsigned long>(phase));
    assert(recovered);
    assert(pair.a.driver.isRunning() && pair.b.driver.isRunning()
           && !pair.a.driver.isPowerSuspended() && !pair.b.driver.isPowerSuspended());
    assert(pair.a.manager.allocations == 0 && pair.b.manager.allocations == 0);
    if (phase == 18000) {
      // Two-second fixed windows never overlap here. Recovery MUST use the
      // scheduled long receive window, not coincident random clocks.
      assert(pair.a.resumes >= 8 || pair.b.resumes >= 8);
      assert(pair.dropped_while_stopped > 0);
    }
  }
  printf("326 deterministic phases; maximum recovery=%lu ms\n", static_cast<unsigned long>(max_recovery));
}

void recovery_test() {
  // Same-phase simultaneous PINGs are handled without requiring a master.
  now_ms = 0; Pair pair;
  for (; now_ms < 1000 && !pair.confirmed(); now_ms += 10) pair.tick();
  assert(pair.confirmed());
  assert(pair.a.driver._peer_session == B_SESSION && pair.b.driver._peer_session == A_SESSION);
  // Restart creates a different boot session, while the surviving endpoint
  // uses its current challenge rather than a stale ACK from the old peer.
  pair.b.driver.end(); pair.b.driver.setHeartbeatSession(C_SESSION); pair.b.driver.begin();
  assert(!pair.b.driver._have_ack);
  for (; now_ms < 40000 && (!pair.b.confirmed() || pair.a.driver._peer_session != C_SESSION); now_ms += 10)
    pair.tick();
  assert(pair.confirmed() && pair.a.driver._peer_session == C_SESSION);

  // A stock replacement continuing ordinary RX, but not answering challenges,
  // must revoke historical negotiated sleep. A later real ACK re-arms it.
  now_ms = 0; Pair replacement; replacement.negotiate(); replacement.cable = false;
  now_ms = replacement.a.driver._last_ack + hb::ACTIVE_PING_MS + hb::ACK_MAX_AGE_MS + 1;
  replacement.a.uart.feed(data_frame({11, 22, 33})); replacement.a.tick(true, 1000);
  assert(!replacement.a.driver._have_ack && replacement.a.driver._peer_session == 0);
  assert(replacement.a.status().find("armed=off") != std::string::npos);
  now_ms += 500000; replacement.a.tick(true, 1000);
  assert(replacement.a.driver.isRunning() && !replacement.a.driver.isPowerSuspended());
  replacement.cable = true;
  const auto restored_at = now_ms;
  for (uint32_t elapsed = 0; elapsed < 35000 && !replacement.confirmed(); elapsed += 10) {
    now_ms = restored_at + elapsed; replacement.tick();
  }
  assert(replacement.confirmed()); replacement.a.tick(true, 300000);
  assert(replacement.a.status().find("armed=on") != std::string::npos);

  now_ms = 0; Pair heartbeat_off; heartbeat_off.negotiate();
  heartbeat_off.a.driver.setHeartbeatEnabled(false);
  now_ms += 500000; heartbeat_off.a.tick(true, 1000, true);
  assert(heartbeat_off.a.driver.isRunning() && !heartbeat_off.a.driver.isPowerSuspended());
  assert(heartbeat_off.a.status().find("armed=off") != std::string::npos);

  // After loss/offline standby, restoring wire connectivity wakes NEITHER
  // endpoint. Periodic timed rendezvous alone restores the link.
  now_ms = 0; Pair sleeping; sleeping.negotiate(); sleeping.cable = false;
  const auto sleep_at = now_ms + 300001;
  sleeping.a.enter_standby(sleep_at, false); sleeping.b.enter_standby(sleep_at + 17000, false);
  sleeping.drop_controls = 3;
  bool recovered = false;
  for (uint32_t elapsed = 0; elapsed <= 660000; elapsed += 50) {
    now_ms = sleep_at + 17000 + elapsed;
    if (elapsed == 40000) sleeping.cable = true;
    sleeping.tick();
    if (sleeping.confirmed()) { recovered = true; break; }
  }
  assert(recovered && sleeping.drop_controls == 0);

  // A failed physical UART begin leaves standby and its saved intent intact;
  // no tight loop retry, and the later timed successful begin recovers.
  now_ms = 0; Peer retry(A_SESSION); retry.enter_standby(0);
  now_ms = 30000;
  const auto resume = retry.driver.servicePowerPolicy(true, 300000, now_ms, true);
  assert(resume == Action::Resume);
  retry.uart.begin_ok = false; retry.driver.begin();
  assert(!retry.driver.isRunning()); retry.driver.completePowerAction(resume, false, now_ms);
  now_ms = 34999;
  assert(retry.driver.servicePowerPolicy(true, 300000, now_ms, true) == Action::None);
  retry.uart.begin_ok = true; now_ms = 35000; retry.tick(true, 300000, true);
  assert(retry.driver.isRunning() && !retry.driver.isPowerSuspended());
  assert(retry.status().find("state=probing") != std::string::npos);
  // Turning the feature off while suspended must immediately resume, rather
  // than persisting an accidental hard-disable or waiting 30 seconds.
  now_ms = 0; Peer off(B_SESSION); off.enter_standby(0);
  now_ms = 5; off.tick(false);
  assert(off.driver.isRunning() && !off.driver.isPowerSuspended());
  off.driver.loop(); assert(off.uart.tx.size() == hb::FRAME_SIZE);
  assert(off.status().find("heartbeat=on") != std::string::npos); // Independent of autosleep.

  // Staggered boot + missed initial traffic recovers on next active heartbeat.
  now_ms = 0; Pair boot; boot.b.driver.end(); boot.b.enabled = false;
  for (; now_ms < 120000; now_ms += 100) boot.tick();
  assert(!boot.a.confirmed() && !boot.b.confirmed());
  boot.b.enabled = true; boot.b.driver.setHeartbeatSession(C_SESSION); boot.b.driver.begin();
  for (const uint32_t end = now_ms + 35000; now_ms < end && !boot.confirmed(); now_ms += 100) boot.tick();
  assert(boot.confirmed());
}

void counter_cycle_test() {
  constexpr uint64_t FULL_CYCLE = UINT64_C(1) << 32;
  // Keep an absolute reference clock in this test so setting the 32-bit mock
  // back near an old timestamp explicitly means 49.7 days elapsed, not a
  // backwards wall-clock change. No RX occurs during that entire gap.
  now_ms = 100; Pair pair; pair.negotiate(); pair.cable = false;
  auto& heartbeat = pair.a;
  const uint32_t ack_at = heartbeat.driver._last_ack;
  assert(heartbeat.driver._ack_fresh && heartbeat.driver._have_ack);
  uint64_t absolute = static_cast<uint64_t>(ack_at) + heartbeat.driver._idle_ms + 1;
  now_ms = static_cast<uint32_t>(absolute); heartbeat.driver.loop();
  assert(!heartbeat.driver._ack_fresh && heartbeat.driver._have_ack);
  assert(heartbeat.status().find("peer=unknown") != std::string::npos);
  heartbeat.driver.end();
  absolute = static_cast<uint64_t>(ack_at) + FULL_CYCLE + 5;
  now_ms = static_cast<uint32_t>(absolute);
  assert(static_cast<uint32_t>(now_ms - ack_at) == 5); // Naive age would look fresh again.
  heartbeat.driver.loop(); // Ended UART loop cannot fabricate new presence.
  const auto resume = heartbeat.driver.servicePowerPolicy(true, 300000, now_ms);
  assert(resume == Action::Resume);
  assert(!heartbeat.driver._ack_fresh && heartbeat.driver._have_ack);
  assert(heartbeat.status().find("peer=unknown") != std::string::npos);
  heartbeat.driver.begin(); heartbeat.driver.completePowerAction(resume, true, now_ms);
  heartbeat.driver.loop();
  assert(!heartbeat.driver._ack_fresh && heartbeat.driver._have_ack);
  const auto fresh_challenge = heartbeat.driver._outstanding_challenge;
  assert(fresh_challenge != 0);
  now_ms += 10;
  heartbeat.uart.feed(control('A', B_SESSION, A_SESSION, fresh_challenge)); heartbeat.driver.loop();
  assert(heartbeat.driver._ack_fresh && heartbeat.confirmed()); // Real RX alone refreshes it.

  // The owner's policy must expire presence even if the physical UART is
  // already ended and loop() therefore returns before any normal processing.
  now_ms = 500; Peer stopped(C_SESSION); stopped.driver.loop();
  const auto challenge = stopped.driver._outstanding_challenge;
  stopped.uart.feed(control('A', B_SESSION, C_SESSION, challenge)); stopped.driver.loop();
  assert(stopped.driver._ack_fresh && stopped.confirmed());
  const auto stopped_ack_at = stopped.driver._last_ack;
  stopped.driver.end();
  absolute = static_cast<uint64_t>(stopped_ack_at) + stopped.driver._idle_ms + 1;
  now_ms = static_cast<uint32_t>(absolute);
  const auto stopped_action = stopped.driver.servicePowerPolicy(true, 300000, now_ms);
  assert(stopped_action == Action::Resume && !stopped.driver._ack_fresh && stopped.driver._have_ack);
  absolute = static_cast<uint64_t>(stopped_ack_at) + FULL_CYCLE + 5;
  now_ms = static_cast<uint32_t>(absolute);
  stopped.driver.servicePowerPolicy(true, 300000, now_ms);
  assert(!stopped.driver._ack_fresh && stopped.driver._have_ack);
  assert(stopped.status().find("peer=unknown") != std::string::npos);

  // Legacy inbound reachability also has sticky expiry, independently of the
  // historical fact that a legacy packet was observed in the distant past.
  now_ms = 1000; Peer legacy(A_SESSION); legacy.driver.setHeartbeatEnabled(false);
  legacy.uart.feed(data_frame({19, 20, 21})); legacy.driver.loop();
  assert(legacy.driver._legacy_rx && legacy.driver._legacy_fresh);
  assert(legacy.status().find("peer=legacy") != std::string::npos);
  const uint32_t legacy_at = legacy.driver._last_legacy_rx;
  legacy.driver.end();
  absolute = static_cast<uint64_t>(legacy_at) + legacy.driver._idle_ms + 1;
  now_ms = static_cast<uint32_t>(absolute);
  const auto legacy_resume = legacy.driver.servicePowerPolicy(false, 300000, now_ms);
  assert(legacy_resume == Action::Resume && !legacy.driver._legacy_fresh && legacy.driver._legacy_rx);
  absolute = static_cast<uint64_t>(legacy_at) + FULL_CYCLE + 5;
  now_ms = static_cast<uint32_t>(absolute);
  legacy.driver.servicePowerPolicy(false, 300000, now_ms);
  assert(static_cast<uint32_t>(now_ms - legacy_at) == 5);
  assert(!legacy.driver._legacy_fresh && legacy.driver._legacy_rx);
  assert(legacy.status().find("peer=unknown") != std::string::npos);
  legacy.driver.begin(); legacy.driver.completePowerAction(legacy_resume, true, now_ms);
  legacy.driver.loop(); assert(!legacy.driver._legacy_fresh);
  legacy.uart.feed(data_frame({22, 23, 24})); legacy.driver.loop();
  assert(legacy.driver._legacy_fresh && !legacy.driver._have_ack);
  assert(legacy.status().find("peer=legacy") != std::string::npos);
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string name = argv[1];
  if (name == "codec") codec_test();
  else if (name == "policy") policy_test();
  else if (name == "compatibility") compatibility_test();
  else if (name == "peer-proof") peer_proof_test();
  else if (name == "bounded-io") bounded_io_test();
  else if (name == "rendezvous") rendezvous_test();
  else if (name == "recovery") recovery_test();
  else if (name == "counter-cycle") counter_cycle_test();
  else assert(false);
  printf("%s passed\n", name.c_str());
}
