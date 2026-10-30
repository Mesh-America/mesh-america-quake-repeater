#!/usr/bin/env python3
"""Run the C3 compact-held-DM policy through the real Companion methods."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def block(text, signature):
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class CompactHeldDmTest(unittest.TestCase):
    def test_independent_capacity_fifo_promotion_metadata_ack_and_retry_dedup(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        header = (ROOT / "examples/companion_radio/MyMesh.h").read_text()
        methods = "\n".join(block(source, signature) for signature in (
            "bool MyMesh::Frame::isChannelMsg() const",
            "int MyMesh::getOfflineQueueCapacity() const",
            "MyMesh::Frame& MyMesh::offlineQueueFrameAt(int logical_index)",
            "bool MyMesh::addToOfflineQueue(const uint8_t frame[], int len)",
            "int MyMesh::peekOfflineQueue(uint8_t frame[])",
            "void MyMesh::popOfflineQueue()",
            "int MyMesh::getFromOfflineQueue(uint8_t frame[])",
            "void MyMesh::forgetVerifiedPendingSender(const uint8_t* pub_key)",
            "void MyMesh::makeOneKeyDMId(uint8_t id[ONE_KEY_DM_ID_SIZE], uint32_t timestamp,",
            "bool MyMesh::wasDeliveredOneKeyDM(const uint8_t* pub_key,",
            "void MyMesh::rememberDeliveredOneKeyDM(const uint8_t* pub_key,",
            "bool MyMesh::onAddressedTextPacket(mesh::Packet* packet, uint8_t src_hash,",
            "void MyMesh::releaseHeldOneKeyDMs()",
            "void MyMesh::onMessageRecv(const ContactInfo &from, mesh::Packet *pkt, uint32_t sender_timestamp,",
        ))
        harness = r'''
#include <helpers/BorrowableFrameBuffer.h>
#include <openssl/sha.h>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#define ONE_KEY_DM_COMPACT_HELD 1
#define ONE_KEY_DM_SHARED_OFFLINE_QUEUE 0
#define OTA_SHARED_COMPANION_QUEUE 1
#define OFFLINE_QUEUE_SIZE 224
#define MAX_FRAME_SIZE 176
#define MAX_PACKET_PAYLOAD 184
#define MAX_TEXT_LEN 160
#define PUB_KEY_SIZE 32
#define TXT_TYPE_PLAIN 0
#define ROUTE_TYPE_DIRECT 2
#define ROUTE_TYPE_FLOOD 1
#define MESH_ENABLE_ONE_KEY_DM 1
#define MESH_ENABLE_LOST_REPLY 0
#define RESP_CODE_CHANNEL_MSG_RECV 0x8c
#define RESP_CODE_CHANNEL_MSG_RECV_V3 0x90
#define RESP_CODE_CHANNEL_DATA_RECV 0x8d
#define MESH_DEBUG_PRINTLN(...) ((void)0)
namespace mesh {
struct Packet {
  uint8_t header = ROUTE_TYPE_FLOOD;
  uint8_t path_len = 0;
  int8_t _snr = 0;
  bool isRouteFlood() const { return header == ROUTE_TYPE_FLOOD; }
};
struct Utils {
  static bool authentic;
  static int MACThenDecrypt(const uint8_t*, uint8_t* out,
                            const uint8_t* in, size_t len) {
    if (!authentic) return 0;
    memcpy(out, in, len);
    return static_cast<int>(len);
  }
  static void sha256(uint8_t* out, size_t size, const uint8_t* a, size_t a_size,
                     const uint8_t* b, size_t b_size) {
    std::vector<uint8_t> input(a, a + a_size);
    input.insert(input.end(), b, b + b_size);
    uint8_t digest[SHA256_DIGEST_LENGTH];
    SHA256(input.data(), input.size(), digest);
    memcpy(out, digest, size);
  }
};
bool Utils::authentic = true;
namespace ota { struct OtaContext { uint8_t bytes[11284]; }; }
}
struct ContactInfo { struct { uint8_t pub_key[PUB_KEY_SIZE] = {}; } id; };
struct SelfIdentity {
  void calcSharedSecret(uint8_t* secret, const uint8_t*) { memset(secret, 0, PUB_KEY_SIZE); }
};
struct Delivery {
  uint32_t timestamp;
  std::string text;
  uint8_t route, path;
  int8_t snr;
};
class MyMesh {
public:
  static constexpr uint8_t MAX_HELD_ONE_KEY_DMS = 15;
  static constexpr uint8_t ONE_KEY_DM_ID_SIZE = 8;
  struct Frame {
    uint8_t len = 0, buf[MAX_FRAME_SIZE] = {};
    bool isChannelMsg() const;
  };
  @HELD@;
  @DELIVERED@;
  static_assert(sizeof(HeldOneKeyDM) == 204, "15 slots must save 1740 bytes");
  mesh::BorrowableFrameBuffer<Frame, 224, 128, mesh::ota::OtaContext> offline_queue;
  int offline_queue_len = 0, offline_queue_head = 0;
  HeldOneKeyDM held_dms[MAX_HELD_ONE_KEY_DMS] = {};
  uint8_t held_dm_count = 0;
  uint8_t verified_pending_keys[MAX_HELD_ONE_KEY_DMS][PUB_KEY_SIZE] = {};
  uint8_t verified_pending_count = 1;
  DeliveredOneKeyDM delivered_dms[MAX_HELD_ONE_KEY_DMS] = {};
  uint8_t delivered_dm_count = 0, delivered_dm_next = 0;
  std::vector<Delivery> deliveries;
  std::vector<std::array<uint8_t, 4>> acks;
  bool accepted = false;
  unsigned writes = 0, active = 0;
  ContactInfo contact;
  SelfIdentity self_id;
  MyMesh() {
    for (unsigned i = 0; i < PUB_KEY_SIZE; ++i)
      contact.id.pub_key[i] = verified_pending_keys[0][i] = 0x42 + i;
  }
  int getOfflineQueueCapacity() const;
  Frame& offlineQueueFrameAt(int index);
  bool addToOfflineQueue(const uint8_t frame[], int len);
  int peekOfflineQueue(uint8_t frame[]);
  void popOfflineQueue();
  int getFromOfflineQueue(uint8_t frame[]);
  bool onAddressedTextPacket(mesh::Packet*, uint8_t, const uint8_t*, size_t);
  void releaseHeldOneKeyDMs();
  void forgetVerifiedPendingSender(const uint8_t*);
  static void makeOneKeyDMId(uint8_t[ONE_KEY_DM_ID_SIZE], uint32_t, const char*);
  bool wasDeliveredOneKeyDM(const uint8_t*, const uint8_t[ONE_KEY_DM_ID_SIZE]) const;
  void rememberDeliveredOneKeyDM(const uint8_t*, const uint8_t[ONE_KEY_DM_ID_SIZE]);
  void onMessageRecv(const ContactInfo&, mesh::Packet*, uint32_t, const char*);
  ContactInfo* lookupPersistentContactByPubKey(const uint8_t* key, size_t) {
    return accepted && !memcmp(contact.id.pub_key, key, PUB_KEY_SIZE) ? &contact : nullptr;
  }
  void markConnectionActive(const ContactInfo&) { ++active; }
  void scheduleContactWrite(const ContactInfo&) { ++writes; }
  bool queueMessage(const ContactInfo&, uint8_t, mesh::Packet* packet,
                     uint32_t timestamp, const uint8_t*, int, const char* text) {
    uint8_t frame[MAX_FRAME_SIZE] = {1}; // private, never evicted as a channel
    memcpy(frame + 1, &timestamp, 4);
    memcpy(frame + 5, text, strlen(text));
    if (!addToOfflineQueue(frame, 5 + strlen(text))) return false;
    deliveries.push_back({timestamp, text, packet->header, packet->path_len, packet->_snr});
    return true;
  }
  void sendAckTo(const ContactInfo&, const uint8_t* hash, uint8_t length) {
    assert(length == 4);
    std::array<uint8_t, 4> ack;
    memcpy(ack.data(), hash, 4);
    acks.push_back(ack);
  }
  void fill() {
    const uint8_t frame = 1;
    while (offline_queue_len < getOfflineQueueCapacity()) assert(addToOfflineQueue(&frame, 1));
  }
  void drain() { uint8_t frame[MAX_FRAME_SIZE]; while (getFromOfflineQueue(frame)) {} }
};
@METHODS@
struct Message {
  uint32_t timestamp;
  std::string text;
  mesh::Packet packet;
  std::vector<uint8_t> plain;
  std::array<uint8_t, 4> ack;
  Message(unsigned id, size_t length = 0) : timestamp(id) {
    text = length ? std::string(length, 'x') : "message-" + std::to_string(id);
    if (length) { text[length - 2] = char(0xC3); text[length - 1] = char(0xA9); }
    plain.resize(5 + text.size());
    memcpy(plain.data(), &timestamp, 4);
    plain[4] = id % 4; // real attempt bits must survive in the exact ACK
    memcpy(plain.data() + 5, text.data(), text.size());
    packet.header = id % 2 ? ROUTE_TYPE_DIRECT : ROUTE_TYPE_FLOOD;
    packet.path_len = id % 2 ? 21 : 0x82;
    packet._snr = id % 2 ? -91 : 51;
    // Independently concatenate and hash exactly the original plaintext/key.
    std::vector<uint8_t> input = plain;
    for (unsigned i = 0; i < PUB_KEY_SIZE; ++i) input.push_back(0x42 + i);
    uint8_t digest[SHA256_DIGEST_LENGTH];
    SHA256(input.data(), input.size(), digest);
    memcpy(ack.data(), digest, 4);
  }
  bool hold(MyMesh& receiver) {
    return receiver.onAddressedTextPacket(&packet, 0x42, plain.data(), plain.size());
  }
};
int main() {
  {
    MyMesh receiver;
    std::vector<Message> messages;
    for (unsigned i = 1; i <= 16; ++i) {
      messages.emplace_back(i, i == 16 ? MAX_TEXT_LEN : 0);
      assert(messages.back().hold(receiver));
    }
    assert(receiver.held_dm_count == 15 && receiver.held_dms[0].timestamp == 2);
    assert(receiver.held_dms[14].text[MAX_TEXT_LEN] == 0);
    auto original_ack = receiver.held_dms[14].ack_hash[0];
    messages.back().plain[4] ^= 1; // same text/timestamp, different attempt
    assert(messages.back().hold(receiver));
    assert(receiver.held_dm_count == 15 && receiver.held_dms[14].ack_hash[0] == original_ack);
    // Pending storage stays independent even with every normal slot occupied.
    receiver.fill();
    assert(receiver.offline_queue_len == 224 && receiver.held_dm_count == 15);
    receiver.accepted = true;
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.verified_pending_count == 0 && receiver.held_dm_count == 15);
    assert(receiver.deliveries.empty() && receiver.acks.empty());
    receiver.popOfflineQueue();
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.held_dm_count == 14 && receiver.offline_queue_len == 224);
    assert(receiver.deliveries.size() == 1 && receiver.deliveries[0].timestamp == 2);
    receiver.drain();
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.held_dm_count == 0 && receiver.deliveries.size() == 15);
    assert(receiver.acks.size() == 15 && receiver.offline_queue_len == 14);
    for (unsigned i = 0; i < 15; ++i) {
      const Delivery& delivery = receiver.deliveries[i];
      const Message& expected = messages[i + 1];
      assert(delivery.timestamp == expected.timestamp && delivery.text == expected.text);
      assert(delivery.route == expected.packet.header && delivery.snr == expected.packet._snr);
      assert(delivery.path == (expected.packet.isRouteFlood() ? expected.packet.path_len : 0));
      assert(receiver.acks[i] == expected.ack);
    }
  }
  {
    MyMesh receiver;
    Message message(7, MAX_TEXT_LEN);
    assert(message.hold(receiver));
    receiver.fill();
    receiver.accepted = true;
    receiver.onMessageRecv(receiver.contact, &message.packet, message.timestamp, message.text.c_str());
    assert(receiver.deliveries.empty() && receiver.held_dm_count == 1);
    receiver.popOfflineQueue();
    receiver.onMessageRecv(receiver.contact, &message.packet, message.timestamp, message.text.c_str());
    assert(receiver.deliveries.size() == 1 && receiver.offline_queue_len == 224);
    receiver.drain();
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.held_dm_count == 0 && receiver.deliveries.size() == 1);
    assert(receiver.acks.size() == 1 && receiver.acks[0] == message.ack);
    receiver.onMessageRecv(receiver.contact, &message.packet, message.timestamp, message.text.c_str());
    assert(receiver.deliveries.size() == 1); // already delivered retry stays deduplicated
  }
  {
    MyMesh receiver;
    Message message(33, MAX_TEXT_LEN);
    mesh::Utils::authentic = false;
    assert(!message.hold(receiver) && receiver.held_dm_count == 0);
    mesh::Utils::authentic = true;
    Message oversized(34, MAX_TEXT_LEN + 1);
    assert(!oversized.hold(receiver) && receiver.held_dm_count == 0);
    assert(!receiver.onAddressedTextPacket(&message.packet, 0x99,
        message.plain.data(), message.plain.size()));
    message.plain[4] = 4; // non-plain text must not enter the compact FIFO
    assert(!message.hold(receiver) && receiver.held_dm_count == 0);
    message.plain[4] = 1;
    assert(message.hold(receiver));
    receiver.fill();
    for (unsigned i = 0; i < 96; ++i) receiver.popOfflineQueue();
    auto* workspace = receiver.offline_queue.acquire(receiver.offline_queue_len,
                                                     receiver.offline_queue_head);
    assert(workspace && receiver.getOfflineQueueCapacity() == 128);
    memset(workspace->bytes, 0xCC, sizeof workspace->bytes);
    assert(!strcmp(receiver.held_dms[0].text, message.text.c_str()));
    receiver.offline_queue.release(receiver.offline_queue_head);
    assert(receiver.getOfflineQueueCapacity() == 224);
    receiver.drain();
    receiver.accepted = true;
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.deliveries.size() == 1 && receiver.deliveries[0].text == message.text);
    assert(receiver.acks.size() == 1 && receiver.acks[0] == message.ack);
  }
  {
    MyMesh receiver;
    Message first(50), second(50, 24);
    assert(first.hold(receiver) && second.hold(receiver));
    assert(receiver.held_dm_count == 2); // equal timestamps do not merge different text
    assert(first.hold(receiver) && receiver.held_dm_count == 2);
    receiver.accepted = true;
    receiver.releaseHeldOneKeyDMs();
    assert(receiver.deliveries.size() == 2 && receiver.acks.size() == 2);
    assert(receiver.deliveries[0].text == first.text && receiver.deliveries[1].text == second.text);
  }
}
'''
        harness = harness.replace("@HELD@", block(header, "struct HeldOneKeyDM {"))
        harness = harness.replace("@DELIVERED@", block(header, "struct DeliveredOneKeyDM {"))
        harness = harness.replace("@METHODS@", methods)
        with tempfile.TemporaryDirectory(prefix="meshcore-compact-dm-") as temp:
            binary = Path(temp) / "compact"
            built = subprocess.run([
                "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-g", "-I", str(ROOT / "src"),
                "-x", "c++", "-", "-lcrypto", "-o", str(binary),
            ], input=harness, text=True, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
