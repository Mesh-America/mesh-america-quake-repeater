#!/usr/bin/env python3
"""Execute repeater discovery policy and wire replies from the production source.

The real handler, hidden-node predicate and rate limiter run unchanged. Only
the radio, packet allocation, identity and clock boundaries are host doubles.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include "examples/simple_repeater/RateLimiter.h"
@CONSTANTS@
#define MESH_DEBUG_PRINTLN(...) ((void)0)
static uint32_t now_ms = 100;
bool millisHasNowPassed(uint32_t deadline) {
  return static_cast<int32_t>(now_ms - deadline) > 0;
}
static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "discovery contract: %s\n", message);
    std::exit(1);
  }
}
namespace mesh {
struct Identity {
  uint8_t pub_key[PUB_KEY_SIZE] = {};
  Identity() = default;
  explicit Identity(const uint8_t* key) { std::memcpy(pub_key, key, PUB_KEY_SIZE); }
  bool matches(const Identity& other) const {
    return std::memcmp(pub_key, other.pub_key, PUB_KEY_SIZE) == 0;
  }
};
struct Packet {
  uint8_t payload[64] = {};
  uint8_t payload_len = 0;
  int8_t _snr = -20;
  float getSNR() const { return _snr / 4.0f; }
  int getRSSI() const { return -90; }
};
}
struct MyMesh {
  struct {
    uint16_t advert_interval = 30, flood_advert_interval = 0;
    bool disable_fwd = false;
    uint32_t discovery_mod_timestamp = 500;
  } _prefs;
  struct Clock {
    uint32_t now = 1000;
    uint32_t getCurrentTime() const { return now; }
  } rtc_clock;
  RateLimiter @LIMITER@;
  mesh::Identity self_id, neighbour;
  mesh::Packet response;
  uint32_t pending_discover_tag = 0, pending_discover_until = 1000;
  unsigned create_attempts = 0, sent_packets = 0, neighbours = 0;
  uint32_t sent_delay = 0, neighbour_timestamp = 0;
  float neighbour_snr = 0;
  int neighbour_rssi = 0;
  bool fail_allocation = false;
  MyMesh() {
    for (size_t i = 0; i < PUB_KEY_SIZE; ++i) self_id.pub_key[i] = 0x60 + i;
  }
  @HIDDEN@
  void onControlDataRecv(mesh::Packet* packet);
  mesh::Packet* createControlData(const uint8_t* bytes, size_t length) {
    ++create_attempts;
    if (fail_allocation) return nullptr;
    require(length <= sizeof(response.payload), "reply exceeded packet capacity");
    std::memcpy(response.payload, bytes, length);
    response.payload_len = length;
    return &response;
  }
  uint32_t getRetransmitDelay(mesh::Packet* packet) {
    require(packet == &response, "delay used the wrong reply packet");
    return 7;
  }
  void sendZeroHop(mesh::Packet* packet, uint32_t delay) {
    require(packet == &response, "radio sent the wrong reply packet");
    ++sent_packets;
    sent_delay = delay;
  }
  void putNeighbour(const mesh::Identity& id, uint32_t timestamp, float snr, int rssi) {
    ++neighbours;
    neighbour = id;
    neighbour_timestamp = timestamp;
    neighbour_snr = snr;
    neighbour_rssi = rssi;
  }
};
@HANDLER@
static mesh::Packet request(bool prefix = false, uint32_t since = 0,
                            bool include_since = false) {
  mesh::Packet packet;
  packet.payload[0] = CTL_TYPE_NODE_DISCOVER_REQ | (prefix ? 1 : 0);
  packet.payload[1] = 1 << ADV_TYPE_REPEATER;
  const uint32_t tag = 0x78563412;
  std::memcpy(packet.payload + 2, &tag, sizeof(tag));
  if (include_since) std::memcpy(packet.payload + 6, &since, sizeof(since));
  packet.payload_len = include_since ? 10 : 6;
  return packet;
}
static void policy() {
  for (uint16_t local : {uint16_t(0), uint16_t(30)}) {
    for (uint16_t flood : {uint16_t(0), uint16_t(30)}) {
      for (bool repeat_off : {false, true}) {
        for (bool prefix : {false, true}) {
          MyMesh receiver;
          receiver._prefs.advert_interval = local;
          receiver._prefs.flood_advert_interval = flood;
          receiver._prefs.disable_fwd = repeat_off;
          const bool hidden = local == 0 && flood == 0;
          require(receiver.isHiddenNode() == hidden, "hidden predicate misread advert intervals");
          auto packet = request(prefix);
          receiver.onControlDataRecv(&packet);
          if (hidden) {
            require(receiver.create_attempts == 0 && receiver.sent_packets == 0,
                    "hidden node emitted a discovery response");
          } else {
            require(receiver.create_attempts == 1 && receiver.sent_packets == 1,
                    "visible node or repeat-off observer lost discovery");
          }
        }
      }
    }
  }
}
static void gates() {
  for (size_t length = 0; length < 6; ++length) {
    MyMesh receiver;
    auto packet = request();
    packet.payload_len = length;
    receiver.onControlDataRecv(&packet);
    require(receiver.create_attempts == 0, "truncated request produced a reply");
  }
  for (uint8_t filter : {uint8_t(0), uint8_t(1 << 3)}) {
    MyMesh receiver;
    auto packet = request();
    packet.payload[1] = filter;
    receiver.onControlDataRecv(&packet);
    require(receiver.create_attempts == 0, "unrelated node filter produced a reply");
  }
  for (uint32_t since : {499U, 500U, 501U}) {
    MyMesh receiver;
    auto packet = request(false, since, true);
    receiver.onControlDataRecv(&packet);
    require(receiver.sent_packets == (since <= 500 ? 1U : 0U),
            "discovery timestamp boundary changed");
  }
  MyMesh limited;
  auto packet = request();
  for (unsigned count = 1; count <= 5; ++count) {
    limited.onControlDataRecv(&packet);
    require(limited.sent_packets == (count <= 4 ? count : 4),
            "discovery rate limit changed");
  }
  limited.rtc_clock.now = 1119;
  limited.onControlDataRecv(&packet);
  require(limited.sent_packets == 4, "rate limit expired before two minutes");
  limited.rtc_clock.now = 1120;
  limited.onControlDataRecv(&packet);
  require(limited.sent_packets == 5, "rate limit did not reopen at two minutes");
  MyMesh unrelated;
  packet.payload[0] = 0x70;
  unrelated.onControlDataRecv(&packet);
  require(unrelated.create_attempts == 0, "unrelated control type produced a reply");
}
static void wire() {
  for (bool prefix : {false, true}) {
    MyMesh receiver;
    auto packet = request(prefix);
    receiver.onControlDataRecv(&packet);
    require(receiver.sent_packets == 1, "visible request lost its reply");
    require(receiver.response.payload_len == 6 + (prefix ? 8 : PUB_KEY_SIZE),
            "prefix/full reply length changed");
    require(receiver.response.payload[0] == (CTL_TYPE_NODE_DISCOVER_RESP | ADV_TYPE_REPEATER),
            "reply control type or node type changed");
    require(receiver.response.payload[1] == static_cast<uint8_t>(packet._snr),
            "reply did not preserve signed inbound SNR bytes");
    require(std::memcmp(receiver.response.payload + 2, packet.payload + 2, 4) == 0,
            "reply did not echo the request tag");
    require(std::memcmp(receiver.response.payload + 6, receiver.self_id.pub_key,
                        prefix ? 8 : PUB_KEY_SIZE) == 0,
            "reply did not preserve the public key or prefix");
    require(receiver.sent_delay == 28, "discovery reply lost its widened random delay");
  }
  MyMesh exhausted;
  exhausted.fail_allocation = true;
  auto packet = request();
  exhausted.onControlDataRecv(&packet);
  require(exhausted.create_attempts == 1 && exhausted.sent_packets == 0,
          "allocation failure attempted to transmit a reply");
}
static void received() {
  MyMesh receiver;
  receiver._prefs.advert_interval = 0;
  receiver._prefs.flood_advert_interval = 0;
  receiver.pending_discover_tag = 0x78563412;
  auto packet = request();
  packet.payload[0] = CTL_TYPE_NODE_DISCOVER_RESP | ADV_TYPE_REPEATER;
  packet.payload_len = 6 + PUB_KEY_SIZE;
  std::memset(packet.payload + 6, 0xAB, PUB_KEY_SIZE);
  receiver.onControlDataRecv(&packet);
  require(receiver.neighbours == 1 && receiver.neighbour_timestamp == 1000
          && receiver.neighbour_snr == -5.0f && receiver.neighbour_rssi == -90,
          "hidden node lost matching discovery response bookkeeping");
  require(std::memcmp(receiver.neighbour.pub_key, packet.payload + 6, PUB_KEY_SIZE) == 0,
          "neighbour response public key changed");
  packet.payload[2] ^= 1;
  receiver.onControlDataRecv(&packet);
  packet.payload[2] ^= 1;
  packet.payload_len -= 1;
  receiver.onControlDataRecv(&packet);
  packet.payload_len += 1;
  packet.payload[0] = CTL_TYPE_NODE_DISCOVER_RESP | 3;
  receiver.onControlDataRecv(&packet);
  packet.payload[0] = CTL_TYPE_NODE_DISCOVER_RESP | ADV_TYPE_REPEATER;
  std::memcpy(packet.payload + 6, receiver.self_id.pub_key, PUB_KEY_SIZE);
  receiver.onControlDataRecv(&packet);
  require(receiver.neighbours == 1, "unrelated/truncated/self response added a neighbour");
  now_ms = receiver.pending_discover_until + 1;
  receiver.onControlDataRecv(&packet);
  require(receiver.neighbours == 1 && receiver.pending_discover_tag == 0,
          "expired discovery response retained its pending request");
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  if (std::strcmp(argv[1], "policy") == 0) policy();
  else if (std::strcmp(argv[1], "gates") == 0) gates();
  else if (std::strcmp(argv[1], "wire") == 0) wire();
  else if (std::strcmp(argv[1], "received") == 0) received();
  else return 2;
}
'''


class RepeaterDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise unittest.SkipTest("a host C++17 compiler is required")
        source = (ROOT / "examples/simple_repeater/MyMesh.cpp").read_text()
        header = (ROOT / "examples/simple_repeater/MyMesh.h").read_text()
        handler = extract_braced(source, "void MyMesh::onControlDataRecv(")
        hidden = extract_braced(header, "bool isHiddenNode() const")
        constants = []
        for text, name in (
            (source, "CTL_TYPE_NODE_DISCOVER_REQ"),
            (source, "CTL_TYPE_NODE_DISCOVER_RESP"),
            ((ROOT / "src/helpers/AdvertDataHelpers.h").read_text(), "ADV_TYPE_REPEATER"),
            ((ROOT / "src/MeshCore.h").read_text(), "PUB_KEY_SIZE"),
        ):
            constants.append(re.search(rf"^#define {name}\s+[^\n]+", text, re.M).group())
        limiter = re.search(r"discover_limiter\(\d+,\s*\d+\)", source).group()
        limiter = limiter.replace("(", "{", 1).replace(")", "}", 1)
        mutant, replacements = re.subn(r"&&\s*!isHiddenNode\(\)", "", handler, count=1)
        if replacements != 1:
            raise AssertionError("production discovery handler must contain the hidden-node gate")
        cls.temporary = tempfile.TemporaryDirectory(prefix="repeater-discovery-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binaries = {}
        for name, body in (("production", handler), ("without_hidden_guard", mutant)):
            code = (HARNESS.replace("@CONSTANTS@", "\n".join(constants))
                    .replace("@LIMITER@", limiter)
                    .replace("@HIDDEN@", hidden)
                    .replace("@HANDLER@", body))
            work = Path(cls.temporary.name)
            cpp, binary = work / f"{name}.cpp", work / name
            cpp.write_text(code)
            compiled = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Wno-reorder",
                *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else []),
                "-I", str(ROOT), str(cpp), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            if compiled.returncode != 0:
                raise AssertionError(compiled.stderr)
            cls.binaries[name] = binary

    def run_case(self, case, binary="production"):
        return subprocess.run([str(self.binaries[binary]), case], capture_output=True,
                              text=True, timeout=10)

    def test_advert_visibility_and_repeat_off_observer_policy(self):
        checked = self.run_case("policy")
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_request_filter_timestamp_and_real_rate_limiter(self):
        checked = self.run_case("gates")
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_prefix_full_reply_bytes_delay_and_allocation_failure(self):
        checked = self.run_case("wire")
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_hidden_nodes_still_process_matching_discovery_responses(self):
        checked = self.run_case("received")
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_removed_hidden_protection_fails_the_same_policy_contract(self):
        checked = self.run_case("policy", "without_hidden_guard")
        self.assertEqual(checked.returncode, 1, checked.stderr)
        self.assertIn("hidden node emitted a discovery response", checked.stderr)


if __name__ == "__main__":
    unittest.main()
