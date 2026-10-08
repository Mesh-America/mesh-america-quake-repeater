#include <algorithm>
#include <cassert>
#include <cstring>
#include <iostream>
#include <vector>
#include <helpers/ClientACLResponse.h>

#define REQ_TYPE_GET_ACCESS_LIST 0x05
#define SERVER_RESPONSE_DELAY 300

namespace mesh {
struct Identity {
  uint8_t pub_key[PUB_KEY_SIZE] = {};
  size_t copyHashTo(uint8_t* destination) const {
    *destination = pub_key[0];
    return PATH_HASH_SIZE;
  }
};
struct Utils {
  // Keep packet assembly/admission real; replace only the crypto primitive.
  static int encryptThenMAC(const uint8_t*, uint8_t* destination,
                            const uint8_t* source, int length) {
    const int encrypted = (length + CIPHER_BLOCK_SIZE - 1) / CIPHER_BLOCK_SIZE * CIPHER_BLOCK_SIZE;
    memset(destination, 0, encrypted + CIPHER_MAC_SIZE);
    memcpy(destination + CIPHER_MAC_SIZE, source, length);
    return encrypted + CIPHER_MAC_SIZE;
  }
};
struct Random {
  void random(uint8_t* data, size_t length) { memset(data, 0x99, length); }
};
class Mesh {
  std::vector<Packet*> allocations;
public:
  Identity self_id;
  Random rng;
  bool refuse_allocation = false;
  ~Mesh() { for (auto* packet : allocations) delete packet; }
  Packet* obtainNewPacket() {
    if (refuse_allocation) return nullptr;
    auto* packet = new Packet;
    allocations.push_back(packet);
    return packet;
  }
  uint8_t getContactTxRadio(const Identity&) { return RADIO_TX_AUTO; }
  Random* getRNG() { return &rng; }
  Packet* createPathReturn(const Identity&, const uint8_t*, const uint8_t*, uint8_t,
                           uint8_t, const uint8_t*, size_t);
  Packet* createPathReturn(const uint8_t*, const uint8_t*, const uint8_t*, uint8_t,
                           uint8_t, const uint8_t*, size_t);
  Packet* createDatagram(uint8_t, const Identity&, const uint8_t*, const uint8_t*, size_t);
};
}

struct ClientInfo {
  mesh::Identity id;
  uint8_t permissions = 3;
  uint32_t last_timestamp = 0, last_activity = 0;
  bool isAdmin() const { return (permissions & 7) == 3; }
};
struct ACL {
  std::vector<ClientInfo> clients;
  int getNumClients() const { return clients.size(); }
  ClientInfo* getClientByIdx(int index) { return &clients.at(index); }
};
struct Clock : mesh::RTCClock {
  uint32_t now = 100;
  uint32_t getCurrentTime() override { return now; }
  void setCurrentTime(uint32_t value) override { now = value; }
};
class MyMesh : public mesh::Mesh {
public:
  uint8_t reply_data[MAX_PACKET_PAYLOAD] = {};
  ACL acl;
  ClientInfo sender;
  Clock clock;
  bool refuse_queue = false;
  unsigned queued = 0;
  mesh::Packet* last_reply = nullptr;
  Clock* getRTCClock() { return &clock; }
  int handleRequest(ClientInfo*, uint32_t, uint8_t*, size_t,
                    size_t = mesh::CLIENT_ACL_DIRECT_REPLY_CAPACITY);
  void receive(mesh::Packet*, uint8_t*, size_t);
  bool admit(mesh::Packet* packet) {
    if (!packet || refuse_queue) return false;
    assert(packet->payload_len <= MAX_PACKET_PAYLOAD);
    last_reply = packet;
    ++queued;
    return true;
  }
  bool sendFloodReply(mesh::Packet* packet, unsigned long, uint8_t) { return admit(packet); }
  bool sendClientReply(ClientInfo*, mesh::Packet* packet, unsigned long, uint8_t) { return admit(packet); }
};

#include "production.inc"

static void fill(ACL& acl, unsigned count, bool sparse = false) {
  acl.clients.assign(count, ClientInfo{});
  for (unsigned i = 0; i < count; ++i) {
    for (unsigned j = 0; j < PUB_KEY_SIZE; ++j) acl.clients[i].id.pub_key[j] = (i + j) % 255 + 1;
    if (sparse && i % 3 != 1) acl.clients[i].permissions = 0;
  }
}

static unsigned verify_entries(MyMesh& mesh, int length, size_t capacity) {
  assert(length >= 4 && size_t(length) <= capacity && (length - 4) % 7 == 0);
  uint32_t tag;
  memcpy(&tag, mesh.reply_data, 4);
  assert(tag == 51);
  unsigned offset = 4;
  for (const auto& client : mesh.acl.clients) {
    if (!client.permissions) continue;
    if (offset + 7 > size_t(length)) break;
    assert(!memcmp(mesh.reply_data + offset, client.id.pub_key, 6));
    assert(mesh.reply_data[offset + 6] == client.permissions);
    offset += 7;
  }
  assert(offset == unsigned(length));
  return (length - 4) / 7;
}

static void print_legacy(const uint8_t* body, unsigned count, size_t length) {
  static const char hex[] = "0123456789abcdef";
  std::cout << "LEGACY:" << count << ':';
  for (size_t i = 0; i < length; ++i) std::cout << hex[body[i] >> 4] << hex[body[i] & 15];
  std::cout << '\n';
}

int main() {
  uint8_t query[] = {REQ_TYPE_GET_ACCESS_LIST, 0, 0};
  uint8_t secret[PUB_KEY_SIZE] = {};
  unsigned paths = 0;
  for (bool flood : {false, true}) {
    for (unsigned path_len = 0; path_len < 256; ++path_len) {
      if (!mesh::Packet::isValidPathLen(path_len)) {
        assert(mesh::clientACLReplyCapacity(flood, path_len) == 0);
        continue;
      }
      ++paths;
      for (unsigned clients : {0, 1, 22, 23, 24, 25, 32, 256}) {
        for (bool sparse : {false, true}) {
          MyMesh mesh;
          fill(mesh.acl, clients, sparse);
          const size_t capacity = mesh::clientACLReplyCapacity(flood, path_len);
          const int length = mesh.handleRequest(&mesh.sender, 51, query, sizeof(query), capacity);
          const unsigned count = verify_entries(mesh, length, capacity);
          const unsigned live = std::count_if(mesh.acl.clients.begin(), mesh.acl.clients.end(),
              [](const ClientInfo& client) { return client.permissions != 0; });
          assert(count == std::min(live, unsigned((capacity - 4) / 7)));
          uint8_t path[MAX_PATH_SIZE] = {};
          mesh::Packet* packet = flood
              ? mesh.createPathReturn(mesh.sender.id, secret, path, path_len,
                                      PAYLOAD_TYPE_RESPONSE, mesh.reply_data, length)
              : mesh.createDatagram(PAYLOAD_TYPE_RESPONSE, mesh.sender.id, secret, mesh.reply_data, length);
          assert(packet && packet->payload_len <= MAX_PACKET_PAYLOAD);
          const size_t cipher_bytes = packet->payload_len - 2 * PATH_HASH_SIZE - CIPHER_MAC_SIZE;
          const size_t path_prefix = flood
              ? 2 + (path_len & 63) * ((path_len >> 6) + 1) : 0;
          assert(cipher_bytes >= path_prefix);
          assert(cipher_bytes - path_prefix + 2 <= MAX_FRAME_SIZE);
          if (path_len == 0 && !sparse) {
            // Decode the actual zero-padded encrypted response body, with the
            // reflected tag and flood path envelope removed by Companion.
            const size_t body_offset = 2 * PATH_HASH_SIZE + CIPHER_MAC_SIZE + 4 + (flood ? 2 : 0);
            print_legacy(packet->payload + body_offset, count, packet->payload_len - body_offset);
          }
        }
      }
    }
  }
  assert(paths > 200); // Includes zero hops, 63 hops, 64 bytes and 2/3-byte hashes.

  MyMesh mesh;
  fill(mesh.acl, 32);
  for (uint8_t permission : {0, 1, 2, 4, 5, 6, 7, 255}) {
    mesh.sender.permissions = permission;
    assert(mesh.handleRequest(&mesh.sender, 51, query, sizeof(query)) == 0);
  }
  mesh.sender.permissions = 3;
  uint8_t app_query[] = {REQ_TYPE_GET_ACCESS_LIST, 0, 0, 0xA1, 0xB2, 0xC3, 0xD4};
  const int app_reply = mesh.handleRequest(&mesh.sender, 51, app_query, sizeof(app_query));
  assert(verify_entries(mesh, app_reply, mesh::CLIENT_ACL_DIRECT_REPLY_CAPACITY) == 22);
  assert(mesh.handleRequest(nullptr, 51, query, sizeof(query)) == 0);
  for (size_t length : {0, 1, 2}) assert(mesh.handleRequest(&mesh.sender, 51, query, length) == 0);
  for (unsigned index : {1, 2}) {
    query[index] = 1;
    assert(mesh.handleRequest(&mesh.sender, 51, query, sizeof(query)) == 0);
    query[index] = 0;
  }
  for (size_t capacity = 0; capacity <= MAX_PACKET_PAYLOAD + 10; ++capacity) {
    const int length = mesh.handleRequest(&mesh.sender, 51, query, sizeof(query), capacity);
    if (capacity < 4) assert(length == 0);
    else verify_entries(mesh, length, std::min(capacity, mesh::CLIENT_ACL_DIRECT_REPLY_CAPACITY));
  }

  // The exact receive branch keeps failed allocation/queue attempts retryable.
  for (bool flood : {false, true}) {
    MyMesh target;
    fill(target.acl, 32);
    target.sender.last_timestamp = 50;
    target.sender.last_activity = 12;
    mesh::Packet request;
    request.header = flood ? ROUTE_TYPE_FLOOD : ROUTE_TYPE_DIRECT;
    request.path_len = 0x60; // 32 two-byte hops: maximum 64 route bytes.
    uint8_t data[] = {51, 0, 0, 0, REQ_TYPE_GET_ACCESS_LIST, 0, 0};
    for (size_t length = 0; length < 7; ++length) target.receive(&request, data, length);
    assert(target.sender.last_timestamp == 50 && target.queued == 0);
    target.refuse_allocation = true;
    target.receive(&request, data, sizeof(data));
    assert(target.sender.last_timestamp == 50 && target.sender.last_activity == 12);
    target.refuse_allocation = false;
    target.refuse_queue = true;
    target.receive(&request, data, sizeof(data));
    assert(target.sender.last_timestamp == 50 && target.sender.last_activity == 12);
    target.refuse_queue = false;
    target.receive(&request, data, sizeof(data));
    assert(target.sender.last_timestamp == 51 && target.sender.last_activity == 100 && target.queued == 1);
    target.receive(&request, data, sizeof(data));
    data[0] = 49;
    target.receive(&request, data, sizeof(data));
    assert(target.sender.last_timestamp == 51 && target.queued == 1);
  }

  // Login and the next request use the same production monotonic RTC helper.
  Clock clock;
  const uint32_t login_tag = clock.getCurrentTimeUnique();
  const uint32_t request_tag = clock.getCurrentTimeUnique();
  assert(request_tag > login_tag); // Same-second login does not collide.
  clock.setCurrentTime(10);
  assert(clock.getCurrentTimeUnique() > request_tag); // In-boot clock rollback remains monotonic.
  std::cout << "ACL route and replay checks passed\n";
}
