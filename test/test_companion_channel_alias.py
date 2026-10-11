"""Execute Companion channel aliases with independent SHA-256 test vectors."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]
HASH_NAMES = (
    "#emergency", "#r2-emergency", "#mt-emergency",
    "#custom", "#r2-custom", "#mt-custom",
)

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <helpers/CompanionChannelAlias.h>

struct DigestVector { const char* text; uint8_t digest[32]; };
static const DigestVector vectors[] = { @VECTORS@ };
struct KeyDigestVector { uint8_t key[32]; size_t length; uint8_t digest[32]; };
static const KeyDigestVector key_vectors[] = { @KEY_VECTORS@ };
static void sha256(uint8_t* out, size_t out_length, const uint8_t* in, int in_length) {
  assert(out && in && in_length >= 0 && out_length <= 32);
  for (const auto& vector : vectors) {
    if (strlen(vector.text) == static_cast<size_t>(in_length)
        && !memcmp(vector.text, in, in_length)) {
      memcpy(out, vector.digest, out_length);
      return;
    }
  }
  for (const auto& vector : key_vectors) {
    if (vector.length == static_cast<size_t>(in_length) && !memcmp(vector.key, in, in_length)) {
      memcpy(out, vector.digest, out_length);
      return;
    }
  }
  assert(!"unexpected input to independent SHA-256 oracle");
}
static void hashtagKey(const char* name, uint8_t out[32]) {
  memset(out, 0, 32);
  sha256(out, 16, reinterpret_cast<const uint8_t*>(name), strlen(name));
}
static void assertAlias(const char* name, CompanionChannelKind kind,
                        bool hashtag, const char* tail) {
  const auto parsed = parseCompanionChannelAlias(name);
  assert(parsed.kind == kind);
  assert(parsed.hashtag == hashtag);
  assert(parsed.tail && !strcmp(parsed.tail, tail));
}
static void grammar() {
  assertAlias("", CompanionChannelKind::MeshCore, false, "");
  assert(parseCompanionChannelAlias(nullptr).kind == CompanionChannelKind::Invalid);
  assertAlias("Public", CompanionChannelKind::MeshCore, false, "Public");
  assertAlias("#emergency", CompanionChannelKind::MeshCore, true, "emergency");
  assertAlias("r2-Public", CompanionChannelKind::Radio2, false, "Public");
  assertAlias("#r2-emergency", CompanionChannelKind::Radio2, true, "emergency");
  assertAlias("mt-LongFast", CompanionChannelKind::Meshtext, false, "LongFast");
  assertAlias("#mt-emergency", CompanionChannelKind::Meshtext, true, "emergency");
  // Routing markers must be complete, leading and case-sensitive.
  assertAlias("r2", CompanionChannelKind::MeshCore, false, "r2");
  assertAlias("mt", CompanionChannelKind::MeshCore, false, "mt");
  assertAlias("R2-Public", CompanionChannelKind::MeshCore, false, "R2-Public");
  assertAlias("#MT-emergency", CompanionChannelKind::MeshCore, true, "MT-emergency");
  assertAlias("room-r2-Public", CompanionChannelKind::MeshCore, false, "room-r2-Public");
  for (const auto* name : {"r2-", "#r2-", "mt-", "#mt-",
                           "r2-#room", "mt-#room", "#r2-#room", "#mt-#room",
                           "r2-r2-room", "r2-mt-room", "mt-r2-room", "mt-mt-room",
                           "#r2-r2-room", "#r2-mt-room", "#mt-r2-room", "#mt-mt-room"}) {
    assert(parseCompanionChannelAlias(name).kind == CompanionChannelKind::Invalid);
  }
  puts("PASS grammar");
}
static void canonical() {
  struct Case { const char* display; const char* canonical; };
  const Case cases[] = {{"Public", "Public"}, {"#emergency", "#emergency"},
                        {"r2-Public", "Public"}, {"#r2-emergency", "#emergency"},
                        {"mt-LongFast", "LongFast"}, {"#mt-emergency", "#emergency"}};
  for (const auto& item : cases) {
    char output[40];
    assert(companionChannelCanonicalName(item.display, output, sizeof(output)));
    assert(!strcmp(output, item.canonical));
    // The exact terminating-NUL boundary must be accepted, never truncated.
    assert(companionChannelCanonicalName(item.display, output, strlen(item.canonical) + 1));
    assert(!strcmp(output, item.canonical));
    assert(!companionChannelCanonicalName(item.display, output, strlen(item.canonical)));
  }
  char output[40];
  assert(!companionChannelCanonicalName("#mt-", output, sizeof(output)));
  assert(!companionChannelCanonicalName("#r2-mt-room", output, sizeof(output)));
  assert(!companionChannelCanonicalName("#r2-emergency", nullptr, 40));
  assert(!companionChannelCanonicalName(nullptr, output, sizeof(output)));
  assert(!companionChannelCanonicalName("#r2-emergency", output, 0));
  puts("PASS canonical");
}
static void keys() {
  uint8_t canonical[32], alias[32], key[32], before[32];
  hashtagKey("#emergency", canonical);
  // Fixed published emergency vector also checks the Python-generated oracle.
  const uint8_t emergency[16] = {0xe1,0xad,0x57,0x8d,0x25,0x10,0x8e,0x34,
                                 0x48,0x08,0xf3,0x0d,0xfd,0xaa,0xf9,0x26};
  assert(!memcmp(canonical, emergency, sizeof(emergency)));
  for (const auto* name : {"#r2-emergency", "#mt-emergency"}) {
    hashtagKey(name, alias);
    memcpy(key, alias, 32);
    resolveCompanionChannelKey(name, key, sha256);
    assert(!memcmp(key, canonical, 32));
    // A second resolution of a wire copy must not derive a new key.
    resolveCompanionChannelKey(name, key, sha256);
    assert(!memcmp(key, canonical, 32));
    assert(memcmp(alias, canonical, 16));
  }
  hashtagKey("#custom", canonical);
  for (const auto* name : {"#r2-custom", "#mt-custom"}) {
    hashtagKey(name, key);
    resolveCompanionChannelKey(name, key, sha256);
    assert(!memcmp(key, canonical, 32));
  }
  // Unprefixed hashtag keys and non-hashtag channel keys retain exact bytes.
  hashtagKey("#emergency", key); memcpy(before, key, 32);
  resolveCompanionChannelKey("#emergency", key, sha256);
  assert(!memcmp(key, before, 32));
  for (const auto* name : {"Public", "r2-Public", "mt-LongFast",
                           "#r2-emergency", "#mt-emergency", "#r2-mt-room"}) {
    for (size_t i = 0; i < 16; ++i) key[i] = static_cast<uint8_t>(i + 1);
    memset(key + 16, 0, 16); memcpy(before, key, 32);
    resolveCompanionChannelKey(name, key, sha256);
    assert(!memcmp(key, before, 32));
    // A 256-bit custom PSK whose first half happens to equal the alias hash
    // must remain a 256-bit key, rather than being replaced by a public key.
    hashtagKey("#r2-emergency", key);
    for (size_t i = 16; i < 32; ++i) key[i] = static_cast<uint8_t>(i + 1);
    memcpy(before, key, 32);
    resolveCompanionChannelKey(name, key, sha256);
    assert(!memcmp(key, before, 32));
  }
  puts("PASS keys");
}
static void receive() {
  for (const auto* name : {"Public", "#emergency"}) {
    assert(companionChannelReceivePriority(name, 0) == 0);
    assert(companionChannelReceivePriority(name, 1) == 1);
    assert(companionChannelReceivePriority(name, 0, false) == 0);
    assert(companionChannelReceivePriority(name, 1, false) == 1);
  }
  for (const auto* name : {"r2-Public", "#r2-emergency"}) {
    assert(companionChannelReceivePriority(name, 0) == -1);
    assert(companionChannelReceivePriority(name, 1) == 0);
    assert(companionChannelReceivePriority(name, 0, false) == 0);
    assert(companionChannelReceivePriority(name, 1, false) == 1);
  }
  for (const auto* name : {"mt-LongFast", "#mt-emergency"}) {
    assert(companionChannelReceivePriority(name, 0) == -1);
    assert(companionChannelReceivePriority(name, 1) == -1);
    // Without a configured radio2, either prefix behaves as ordinary MeshCore.
    assert(companionChannelReceivePriority(name, 0, false) == 0);
    assert(companionChannelReceivePriority(name, 1, false) == 1);
  }
  for (const auto* name : {"#mt-", "#r2-mt-emergency"}) {
    for (uint8_t origin : {0, 1}) {
      assert(companionChannelReceivePriority(name, origin, true) == -1);
      assert(companionChannelReceivePriority(name, origin, false) == -1);
    }
  }
  puts("PASS receive");
}
int main(int argc, char** argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "grammar")) grammar();
  else if (!strcmp(argv[1], "canonical")) canonical();
  else if (!strcmp(argv[1], "keys")) keys();
  else if (!strcmp(argv[1], "receive")) receive();
  else assert(!"unknown test case");
}
'''

RUNTIME_HARNESS = r'''
#include <RadioProfiles.h>
#define MAX_GROUP_CHANNELS 5
#define MAX_PACKET_PAYLOAD 255
namespace mesh {
struct GroupChannel { uint8_t secret[32] = {}, hash[1] = {}, tx_radio = RADIO_TX_AUTO; };
struct Packet { uint8_t radio_origin = 0, tx_radio = RADIO_TX_AUTO;
                uint8_t payload[MAX_PACKET_PAYLOAD] = {}; int payload_len = 0; };
struct Utils {
  static void sha256(uint8_t* out, size_t length, const uint8_t* in, int in_length) {
    ::sha256(out, length, in, in_length);
  }
  static bool isZeroes(const uint8_t* bytes, size_t length) {
    for (size_t i = 0; i < length; ++i) if (bytes[i]) return false;
    return true;
  }
  // The native test exercises the caller's authenticated-key gating, while
  // substituting only the cipher primitive with an explicit key-match oracle.
  static int MACThenDecrypt(const uint8_t* key, uint8_t*, const uint8_t* data, int length) {
    return length == 16 && !memcmp(key, data, 16) ? 1 : 0;
  }
};
}
struct ChannelDetails { mesh::GroupChannel channel; char name[32] = {}; };
struct Radio { mesh::RadioProfiles config; bool present = true;
               mesh::RadioProfiles* profiles() { return present ? &config : nullptr; } };
class BaseChatMesh {
public:
  ChannelDetails stored[MAX_GROUP_CHANNELS]; unsigned delivered = 0;
  bool getChannel(int index, ChannelDetails& channel) {
    if (index < 0 || index >= MAX_GROUP_CHANNELS) return false;
    channel = stored[index]; return true;
  }
  bool setChannel(int index, const ChannelDetails& channel) {
    if (index < 0 || index >= MAX_GROUP_CHANNELS) return false;
    stored[index] = channel;
    mesh::Utils::sha256(stored[index].channel.hash, sizeof(stored[index].channel.hash),
                       channel.channel.secret,
                       mesh::Utils::isZeroes(channel.channel.secret + 16, 16) ? 16 : 32);
    return true;
  }
  void onGroupDataRecv(mesh::Packet*, uint8_t, const mesh::GroupChannel&, uint8_t*, size_t) {
    ++delivered;
  }
};
class MyMesh : public BaseChatMesh {
public:
  Radio radio; Radio* _radio = &radio;
  bool isAliasRadio2Defined() const;
  bool resolveChannelAlias(ChannelDetails&) const;
  bool getChannel(int, ChannelDetails&);
  bool setChannel(int, const ChannelDetails&);
  int searchChannelsForPacket(const mesh::Packet*, const uint8_t*, mesh::GroupChannel[], int);
  int findChannelIdxForPacket(const mesh::GroupChannel&, const mesh::Packet*);
  bool allowGroupPacketOnRadio(mesh::Packet*);
  void onGroupDataRecv(mesh::Packet*, uint8_t, const mesh::GroupChannel&, uint8_t*, size_t);
  @SAVE_GETTER@
};
@METHODS@
static ChannelDetails channel(const char* name) {
  ChannelDetails value;
  strcpy(value.name, name);
  hashtagKey(name, value.channel.secret);
  return value;
}
int main() {
  MyMesh node;
  node.radio.config.secondary.mode = mesh::RadioProfileMode::RxTx;
  auto ordinary = channel("#emergency");
  auto secondary = channel("#r2-emergency");
  auto mt = channel("#mt-emergency");
  ordinary.channel.tx_radio = mesh::RADIO_TX_BOTH;
  secondary.channel.tx_radio = mesh::RADIO_TX_PRIMARY;
  mt.channel.tx_radio = mesh::RADIO_TX_BOTH;
  assert(node.setChannel(0, ordinary));
  assert(node.setChannel(1, secondary));
  assert(node.setChannel(2, mt));
  ChannelDetails wire, raw;
  assert(node.getChannel(1, wire));
  assert(wire.channel.tx_radio == mesh::RADIO_TX_SECONDARY);
  assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
  uint8_t expected_hash;
  sha256(&expected_hash, 1, ordinary.channel.secret, 16);
  assert(wire.channel.hash[0] == expected_hash);
  assert(node.getChannelForSave(1, raw));
  assert(!strcmp(raw.name, secondary.name));
  assert(!memcmp(raw.channel.secret, secondary.channel.secret, 32));
  assert(raw.channel.tx_radio == mesh::RADIO_TX_PRIMARY);
  // Applying the raw GET/persistence representation again must be idempotent.
  assert(node.setChannel(1, raw) && node.getChannel(1, wire));
  assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
  assert(node.getChannel(2, wire));
  assert(wire.channel.tx_radio == mesh::RADIO_TX_OFF);
  assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
  assert(node.getChannelForSave(2, raw));
  assert(!memcmp(raw.channel.secret, mt.channel.secret, 32));
  assert(raw.channel.tx_radio == mesh::RADIO_TX_BOTH);
  // Both Rx and RxTx define the secondary profile. The real RadioProfiles
  // transmit permission remains distinct from the channel's routing policy.
  for (auto mode : {mesh::RadioProfileMode::Rx, mesh::RadioProfileMode::RxTx}) {
    node.radio.config.secondary.mode = mode;
    assert(node.isAliasRadio2Defined());
    assert(node.getChannel(0, wire) && wire.channel.tx_radio == mesh::RADIO_TX_BOTH);
    assert(node.getChannel(1, wire) && wire.channel.tx_radio == mesh::RADIO_TX_SECONDARY);
    assert(node.getChannel(2, wire) && wire.channel.tx_radio == mesh::RADIO_TX_OFF);
    assert(node.radio.config.canTransmit(1) == (mode == mesh::RadioProfileMode::RxTx));
  }

  mesh::Packet packet;
  packet.payload[0] = wire.channel.hash[0]; packet.payload_len = 17;
  memcpy(packet.payload + 1, ordinary.channel.secret, 16);
  mesh::GroupChannel matches[4];
  assert(node.allowGroupPacketOnRadio(&packet));
  assert(packet.tx_radio == mesh::RADIO_TX_AUTO); // the ordinary primary slot wins
  assert(node.searchChannelsForPacket(&packet, packet.payload, matches, 4) == 1);
  assert(node.findChannelIdxForPacket(matches[0], &packet) == 0);
  packet.radio_origin = 1;
  assert(node.allowGroupPacketOnRadio(&packet));
  assert(packet.tx_radio == mesh::RADIO_TX_SECONDARY); // bound before local delivery
  assert(node.searchChannelsForPacket(&packet, packet.payload, matches, 4) == 1);
  assert(node.findChannelIdxForPacket(matches[0], &packet) == 1);
  uint8_t data = 0;
  node.onGroupDataRecv(&packet, 0, matches[0], &data, 1);
  assert(node.delivered == 1 && packet.tx_radio == mesh::RADIO_TX_SECONDARY);

  ChannelDetails empty;
  assert(node.setChannel(0, empty));
  packet.tx_radio = mesh::RADIO_TX_AUTO;
  assert(node.allowGroupPacketOnRadio(&packet));
  assert(packet.tx_radio == mesh::RADIO_TX_SECONDARY); // alias-only secondary admission
  packet.radio_origin = 0;
  packet.tx_radio = mesh::RADIO_TX_AUTO;
  assert(!node.allowGroupPacketOnRadio(&packet)); // authenticated alias on wrong radio
  assert(packet.tx_radio == mesh::RADIO_TX_AUTO);
  packet.payload[1] ^= 1;
  assert(node.allowGroupPacketOnRadio(&packet)); // hash match alone is insufficient
  packet.payload[1] ^= 1;
  assert(node.setChannel(1, empty));
  for (uint8_t origin : {0, 1}) {
    packet.radio_origin = origin;
    assert(node.searchChannelsForPacket(&packet, packet.payload, matches, 4) == 0);
    assert(node.findChannelIdxForPacket(wire.channel, &packet) == -1);
    assert(!node.allowGroupPacketOnRadio(&packet)); // configured MT cannot enter MeshCore
    uint8_t blocked_data = 0;
    const auto before_delivery = node.delivered;
    node.onGroupDataRecv(&packet, 0, wire.channel, &blocked_data, 1);
    assert(node.delivered == before_delivery);
  }
  // Both disabled secondary profile and an absent profile ignore routing markers.
  for (bool absent : {false, true}) {
    node.radio.config.secondary.mode = mesh::RadioProfileMode::Off; node.radio.present = !absent;
    assert(!node.isAliasRadio2Defined());
    assert(node.getChannel(2, wire) && wire.channel.tx_radio == mesh::RADIO_TX_BOTH);
    assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
    for (uint8_t origin : {0, 1}) {
      packet.radio_origin = origin;
      assert(node.allowGroupPacketOnRadio(&packet));
      assert(node.searchChannelsForPacket(&packet, packet.payload, matches, 4) == 1);
      assert(node.findChannelIdxForPacket(matches[0], &packet) == 2);
    }
    assert(node.setChannel(1, secondary) && node.getChannel(1, wire));
    assert(wire.channel.tx_radio == mesh::RADIO_TX_PRIMARY);
    assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
    assert(node.setChannel(1, empty));
  }
  // Custom private keys survive both wire resolution and storage access.
  ChannelDetails custom = secondary;
  for (size_t i = 0; i < 16; ++i) custom.channel.secret[i] = static_cast<uint8_t>(i + 1);
  assert(node.setChannel(3, custom) && node.getChannel(3, wire));
  assert(!memcmp(wire.channel.secret, custom.channel.secret, 32));
  assert(node.getChannelForSave(3, raw));
  assert(!memcmp(raw.channel.secret, custom.channel.secret, 32));
  custom = secondary;
  for (size_t i = 16; i < 32; ++i) custom.channel.secret[i] = static_cast<uint8_t>(i + 1);
  assert(node.setChannel(3, custom) && node.getChannel(3, wire));
  assert(!memcmp(wire.channel.secret, custom.channel.secret, 32));
  assert(node.getChannelForSave(3, raw));
  assert(!memcmp(raw.channel.secret, custom.channel.secret, 32));
  strcpy(custom.name, "#r2-mt-room");
  assert(!node.setChannel(3, custom));
  assert(!node.getChannel(-1, wire) && !node.setChannel(MAX_GROUP_CHANNELS, custom));
  puts("PASS runtime raw/wire keys, receive aliases and radio2 fallback");
}
'''

COMMAND_STUBS = r'''
struct StrHelper {
  static void strncpy(char* out, const char* in, size_t length) {
    assert(length > 0);
    ::strncpy(out, in, length - 1); out[length - 1] = 0;
  }
};
struct Serial {
  uint8_t frame[128] = {}; int length = 0;
  void writeFrame(const uint8_t* data, int size) {
    assert(size >= 0 && size <= static_cast<int>(sizeof(frame)));
    memcpy(frame, data, size); length = size;
  }
};
'''

COMMAND_MEMBERS = r'''
  Serial serial; Serial* _serial = &serial;
  bool save_result = true, ok = false; int error = -1; unsigned save_calls = 0;
  bool saveChannels() { ++save_calls; return save_result; }
  void writeErrFrame(uint8_t code) { error = code; }
  void writeOKFrame() { ok = true; }
  void command(uint8_t*, int);
'''

COMMAND_HARNESS = r'''
void MyMesh::command(uint8_t* cmd_frame, int len) {
  uint8_t out_frame[128] = {};
  error = -1; ok = false; serial.length = 0;
  @COMMAND_BRANCHES@
}
static void applySet(MyMesh& node, uint8_t index, const ChannelDetails& value, int key_bytes = 16) {
  uint8_t frame[66] = {CMD_SET_CHANNEL, index};
  memcpy(frame + 2, value.name, 32);
  memcpy(frame + 34, value.channel.secret, key_bytes);
  node.command(frame, 34 + key_bytes);
}
static void expectRaw(MyMesh& node, uint8_t index, const ChannelDetails& expected) {
  ChannelDetails raw;
  assert(node.getChannelForSave(index, raw));
  assert(!strcmp(raw.name, expected.name));
  assert(!memcmp(raw.channel.secret, expected.channel.secret, 32));
  assert(raw.channel.tx_radio == expected.channel.tx_radio);
}
static void expectGet(MyMesh& node, uint8_t index, const ChannelDetails& expected) {
  uint8_t command[2] = {CMD_GET_CHANNEL, index};
  node.command(command, sizeof(command));
  assert(node.error == -1 && !node.ok && node.serial.length == 50);
  assert(node.serial.frame[0] == RESP_CODE_CHANNEL_INFO && node.serial.frame[1] == index);
  assert(!strcmp(reinterpret_cast<const char*>(node.serial.frame + 2), expected.name));
  assert(!memcmp(node.serial.frame + 34, expected.channel.secret, 16));
}
int main() {
  MyMesh node;
  node.radio.config.secondary.mode = mesh::RadioProfileMode::RxTx;
  auto original = channel("#r2-emergency");
  original.channel.tx_radio = mesh::RADIO_TX_BOTH;
  assert(node.setChannel(0, original));
  expectGet(node, 0, original);
  ChannelDetails wire;
  assert(node.getChannel(0, wire));
  assert(memcmp(node.serial.frame + 34, wire.channel.secret, 16)); // GET is not the wire key

  // Switching the display alias without changing the canonical key preserves
  // the user's raw manual policy, not the alias's effective secondary policy.
  auto ordinary = channel("#emergency");
  applySet(node, 0, ordinary);
  assert(node.ok && node.error == -1 && node.save_calls == 1);
  ordinary.channel.tx_radio = mesh::RADIO_TX_BOTH;
  expectRaw(node, 0, ordinary);
  applySet(node, 0, original);
  assert(node.ok && node.error == -1 && node.save_calls == 2);
  expectRaw(node, 0, original);
  expectGet(node, 0, original);

  // Failed persistence restores the exact app representation. In particular,
  // it must not replace the stored prefixed hashtag key with its wire key.
  node.save_result = false;
  const auto replacement = channel("#r2-custom");
  applySet(node, 0, replacement);
  assert(!node.ok && node.error == ERR_CODE_FILE_IO_ERROR && node.save_calls == 3);
  expectRaw(node, 0, original);
  expectGet(node, 0, original);
  node.save_result = true;

  // A genuinely different private PSK resets manual routing to AUTO.
  auto private_channel = original;
  for (size_t i = 0; i < 16; ++i) private_channel.channel.secret[i] = static_cast<uint8_t>(i + 1);
  private_channel.channel.tx_radio = mesh::RADIO_TX_AUTO;
  applySet(node, 0, private_channel);
  assert(node.ok && node.error == -1 && node.save_calls == 4);
  expectRaw(node, 0, private_channel);
  assert(node.getChannel(0, wire));
  assert(!memcmp(wire.channel.secret, private_channel.channel.secret, 32));
  // Reapplying an unchanged private key retains an explicitly saved policy.
  private_channel.channel.tx_radio = mesh::RADIO_TX_PRIMARY;
  assert(node.setChannel(0, private_channel));
  applySet(node, 0, private_channel);
  assert(node.ok && node.error == -1 && node.save_calls == 5);
  expectRaw(node, 0, private_channel);

  auto invalid = private_channel;
  strcpy(invalid.name, "#r2-mt-emergency");
  applySet(node, 0, invalid);
  assert(!node.ok && node.error == ERR_CODE_ILLEGAL_ARG && node.save_calls == 5);
  expectRaw(node, 0, private_channel);
  const auto mt = channel("#mt-emergency");
  applySet(node, 0, mt);
  assert(!node.ok && node.error == ERR_CODE_UNSUPPORTED_CMD && node.save_calls == 5);
  expectRaw(node, 0, private_channel);

  // Disabled or absent radio2 permits the MT display marker only as an
  // ordinary MeshCore channel; it does not activate Meshtext transport.
  node.radio.config.secondary.mode = mesh::RadioProfileMode::Off;
  applySet(node, 0, mt);
  assert(node.ok && node.error == -1 && node.save_calls == 6);
  expectRaw(node, 0, mt);
  expectGet(node, 0, mt);
  assert(node.getChannel(0, wire));
  assert(wire.channel.tx_radio == mesh::RADIO_TX_AUTO);
  assert(!memcmp(wire.channel.secret, ordinary.channel.secret, 32));
  node.radio.present = false;
  applySet(node, 0, mt);
  assert(node.ok && node.error == -1 && node.save_calls == 7);
  expectRaw(node, 0, mt);

  // Binary framing remains 128-bit only; larger keys are not silently cut.
  applySet(node, 0, mt, 32);
  assert(!node.ok && node.error == ERR_CODE_UNSUPPORTED_CMD && node.save_calls == 7);
  expectRaw(node, 0, mt);
  applySet(node, MAX_GROUP_CHANNELS, mt);
  assert(!node.ok && node.error == ERR_CODE_NOT_FOUND && node.save_calls == 7);
  uint8_t bad_get[] = {CMD_GET_CHANNEL, MAX_GROUP_CHANNELS};
  node.command(bad_get, sizeof(bad_get));
  assert(node.error == ERR_CODE_NOT_FOUND && node.serial.length == 0);
  puts("PASS command raw GET, canonical-key SET, rollback and unsupported transport");
}
'''


def oracle_vectors():
    vectors = ",\n".join(
        "{" + json.dumps(name) + ",{" + ",".join(map(str, hashlib.sha256(name.encode()).digest())) + "}}"
        for name in HASH_NAMES
    )
    keys = [hashlib.sha256(name.encode()).digest()[:16] for name in HASH_NAMES]
    keys += [bytes(16), bytes(range(1, 17)),
             hashlib.sha256(b"#r2-emergency").digest()[:16] + bytes(range(17, 33))]
    key_vectors = ",\n".join(
        "{{" + ",".join(map(str, key)) + "}," + str(len(key)) + ",{" +
        ",".join(map(str, hashlib.sha256(key).digest())) + "}}" for key in keys
    )
    return vectors, key_vectors


class CompanionChannelAliasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise unittest.SkipTest("a host C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="meshcore-channel-alias-")
        cls.addClassCleanup(cls.temporary.cleanup)
        work = Path(cls.temporary.name)
        cls.binary = work / ("alias.exe" if sys.platform == "win32" else "alias")
        vectors, key_vectors = oracle_vectors()
        source = work / "alias.cpp"
        source.write_text(HARNESS.replace("@VECTORS@", vectors).replace("@KEY_VECTORS@", key_vectors), encoding="utf-8")
        sanitizers = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
        built = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizers,
             "-I" + str(ROOT / "src"), str(source), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=60,
        )
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    def run_case(self, case):
        checked = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("PASS " + case, checked.stdout)

    def test_prefix_grammar(self):
        self.run_case("grammar")

    def test_canonical_names_and_output_bounds(self):
        self.run_case("canonical")

    def test_independent_sha256_vectors_and_custom_keys(self):
        self.run_case("keys")

    def test_receive_priority_and_unconfigured_radio2_fallback(self):
        self.run_case("receive")

    def test_core_admission_precedes_group_seen_and_direct_forward(self):
        core = (ROOT / "src/Mesh.cpp").read_text(encoding="utf-8")
        received = body(core, "DispatcherAction Mesh::onRecvPacket(Packet* pkt)")
        gate = re.search(
            r"if\s*\(\(pkt->getPayloadType\(\)\s*==\s*PAYLOAD_TYPE_GRP_TXT\s*"
            r"\|\|\s*pkt->getPayloadType\(\)\s*==\s*PAYLOAD_TYPE_GRP_DATA\)\s*"
            r"&&\s*!allowGroupPacketOnRadio\(pkt\)\)\s*return ACTION_RELEASE;", received,
        )
        self.assertIsNotNone(gate, "both encrypted group types must pass admission")
        # TRACE has an unrelated earlier direct block; check the general
        # direct-path branch, whose relaying runs before local group delivery.
        direct = received.index("if (pkt->isRouteDirect() && pkt->getPathHashCount() > 0)")
        group = received.index("case PAYLOAD_TYPE_GRP_DATA:")
        group_seen = received.index("_tables->markSeen(pkt);", group)
        candidates = received.index("searchChannelsForPacket(pkt, &channel_hash, channels, 4)", group)
        delivery = received.index("onGroupDataRecv(pkt,", candidates)
        self.assertLess(gate.end(), direct)
        self.assertLess(gate.end(), group_seen)
        self.assertLess(group_seen, candidates)
        self.assertLess(candidates, delivery)
        header = (ROOT / "src/Mesh.h").read_text(encoding="utf-8")
        self.assertRegex(header, r"virtual bool allowGroupPacketOnRadio\(Packet\* packet\)\s*\{ return true; \}")

    def test_production_channel_access_and_receive_resolution(self):
        companion = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text(encoding="utf-8")
        header = (ROOT / "examples/companion_radio/MyMesh.h").read_text(encoding="utf-8")
        signatures = (
            "bool MyMesh::isAliasRadio2Defined(", "bool MyMesh::resolveChannelAlias(",
            "bool MyMesh::getChannel(", "bool MyMesh::setChannel(",
            "int MyMesh::searchChannelsForPacket(", "int MyMesh::findChannelIdxForPacket(",
            "bool MyMesh::allowGroupPacketOnRadio(", "void MyMesh::onGroupDataRecv(",
        )
        methods = "\n".join(body(companion, signature) for signature in signatures)
        save_getter = body(header, "bool getChannelForSave(uint8_t").replace("override", "")
        shared = HARNESS[:HARNESS.index("static void assertAlias(")]
        vectors, key_vectors = oracle_vectors()
        source_text = (shared + RUNTIME_HARNESS).replace("@VECTORS@", vectors).replace(
            "@KEY_VECTORS@", key_vectors).replace("@METHODS@", methods).replace("@SAVE_GETTER@", save_getter)
        self.run_native_program(source_text, "runtime")

    def test_production_binary_get_set_raw_keys_and_rollback(self):
        companion = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text(encoding="utf-8")
        header = (ROOT / "examples/companion_radio/MyMesh.h").read_text(encoding="utf-8")
        signatures = ("bool MyMesh::isAliasRadio2Defined(", "bool MyMesh::resolveChannelAlias(",
                      "bool MyMesh::getChannel(", "bool MyMesh::setChannel(")
        methods = "\n".join(body(companion, signature) for signature in signatures)
        save_getter = body(header, "bool getChannelForSave(uint8_t").replace("override", "")
        command_signatures = (
            "if (cmd_frame[0] == CMD_GET_CHANNEL && len >= 2)",
            "if (cmd_frame[0] == CMD_SET_CHANNEL && len >= 2 + 32 + 32)",
            "if (cmd_frame[0] == CMD_SET_CHANNEL && len >= 2 + 32 + 16)",
        )
        branches = " else ".join(body(companion, signature) for signature in command_signatures)
        macros = ("CMD_GET_CHANNEL", "CMD_SET_CHANNEL", "RESP_CODE_CHANNEL_INFO",
                  "ERR_CODE_UNSUPPORTED_CMD", "ERR_CODE_NOT_FOUND", "ERR_CODE_FILE_IO_ERROR",
                  "ERR_CODE_ILLEGAL_ARG")
        constants = "\n".join(re.search(r"^#define\s+" + name + r"\s+[^\r\n]+", companion,
                                        flags=re.MULTILINE).group(0) for name in macros)
        shared = HARNESS[:HARNESS.index("static void assertAlias(")]
        fixture = RUNTIME_HARNESS[:RUNTIME_HARNESS.index("\nint main()")]
        fixture = fixture.replace("class MyMesh :", COMMAND_STUBS + "\nclass MyMesh :")
        fixture = fixture.replace("@SAVE_GETTER@", save_getter + "\n" + COMMAND_MEMBERS)
        vectors, key_vectors = oracle_vectors()
        source_text = (shared + constants + "\n" + fixture + COMMAND_HARNESS).replace(
            "@VECTORS@", vectors).replace("@KEY_VECTORS@", key_vectors).replace(
            "@METHODS@", methods).replace("@COMMAND_BRANCHES@", branches)
        self.run_native_program(source_text, "command")

    def run_native_program(self, source_text, expected):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        with tempfile.TemporaryDirectory(prefix="meshcore-channel-runtime-") as directory:
            work = Path(directory)
            source = work / "runtime.cpp"
            source.write_text(source_text, encoding="utf-8")
            binary = work / ("runtime.exe" if sys.platform == "win32" else "runtime")
            sanitizers = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                           "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
            built = subprocess.run(
                [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizers,
                 "-I" + str(ROOT / "src"), str(source), "-o", str(binary)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("PASS " + expected, checked.stdout)


if __name__ == "__main__":
    unittest.main()
