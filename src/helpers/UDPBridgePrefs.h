#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

namespace mesh { namespace bridge { namespace udp {

static constexpr uint8_t MAX_PEERS = 8;
static constexpr uint16_t DEFAULT_PORT = 4404;
static constexpr size_t PREFS_IMAGE_SIZE = 64;

struct Peer {
  uint8_t ip[4] = {};
  uint16_t port = 0;
  bool enabled() const { return port != 0; }
};

struct Prefs {
  uint8_t enabled = 0;
  uint16_t port = DEFAULT_PORT;
  Peer peers[MAX_PEERS];
};

inline bool validAddress(const uint8_t ip[4]) {
  // Subnet-directed broadcasts also depend on the connected interface mask;
  // the runtime transport checks those before sending or accepting a peer.
  return ip && ip[0] != 0 && ip[0] != 127 && ip[0] < 224;
}

inline bool equalPeer(const Peer& a, const Peer& b) {
  return a.port == b.port && memcmp(a.ip, b.ip, 4) == 0;
}

inline bool validPrefs(const Prefs& prefs) {
  if (prefs.enabled > 1 || prefs.port == 0) return false;
  for (uint8_t i = 0; i < MAX_PEERS; ++i) {
    const Peer& peer = prefs.peers[i];
    if (!peer.enabled()) {
      for (uint8_t octet : peer.ip) if (octet != 0) return false;
      continue;
    }
    if (!validAddress(peer.ip)) return false;
    for (uint8_t j = 0; j < i; ++j) {
      if (prefs.peers[j].enabled() && equalPeer(peer, prefs.peers[j])) return false;
    }
  }
  return true;
}

inline bool parsePort(const char* text, uint16_t& result) {
  if (!text || !*text) return false;
  uint32_t value = 0;
  for (; *text; ++text) {
    if (*text < '0' || *text > '9') return false;
    value = value * 10 + static_cast<uint8_t>(*text - '0');
    if (value > 65535) return false;
  }
  if (value == 0) return false;
  result = static_cast<uint16_t>(value);
  return true;
}

inline bool parsePeer(const char* text, Peer& result) {
  if (!text) return false;
  if (strcmp(text, "off") == 0) { result = Peer(); return true; }
  Peer candidate;
  const char* cursor = text;
  for (uint8_t i = 0; i < 4; ++i) {
    unsigned value = 0, digits = 0;
    while (*cursor >= '0' && *cursor <= '9') {
      value = value * 10 + static_cast<uint8_t>(*cursor++ - '0');
      if (++digits > 3 || value > 255) return false;
    }
    if (digits == 0 || *cursor++ != (i == 3 ? ':' : '.')) return false;
    candidate.ip[i] = static_cast<uint8_t>(value);
  }
  if (!validAddress(candidate.ip) || !parsePort(cursor, candidate.port)) return false;
  result = candidate;
  return true;
}

inline void formatPeer(const Peer& peer, char* reply, size_t capacity) {
  if (!peer.enabled()) { snprintf(reply, capacity, "off"); return; }
  snprintf(reply, capacity, "%u.%u.%u.%u:%u", peer.ip[0], peer.ip[1],
      peer.ip[2], peer.ip[3], peer.port);
}

inline bool parseNonce(const char* text, uint32_t& result) {
  if (!text || strlen(text) != 8) return false;
  uint32_t value = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    const char c = text[i];
    uint8_t digit;
    if (c >= '0' && c <= '9') digit = static_cast<uint8_t>(c - '0');
    else if (c >= 'a' && c <= 'f') digit = static_cast<uint8_t>(c - 'a' + 10);
    else if (c >= 'A' && c <= 'F') digit = static_cast<uint8_t>(c - 'A' + 10);
    else return false;
    value = (value << 4) | digit;
  }
  result = value;
  return true;
}

inline uint32_t prefsChecksum(const uint8_t* data, size_t size) {
  uint32_t crc = 0xffffffffU;
  while (size--) {
    crc ^= *data++;
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0);
  }
  return crc;
}

inline void encodePrefs(uint8_t image[PREFS_IMAGE_SIZE], const Prefs& prefs) {
  memset(image, 0, PREFS_IMAGE_SIZE);
  memcpy(image, "UDP1", 4);
  image[4] = prefs.enabled;
  image[6] = prefs.port >> 8; image[7] = prefs.port & 255;
  for (uint8_t i = 0; i < MAX_PEERS; ++i) {
    memcpy(image + 8 + i * 6, prefs.peers[i].ip, 4);
    image[12 + i * 6] = prefs.peers[i].port >> 8;
    image[13 + i * 6] = prefs.peers[i].port & 255;
  }
  const uint32_t crc = prefsChecksum(image, PREFS_IMAGE_SIZE - 4);
  for (uint8_t i = 0; i < 4; ++i) image[60 + i] = (crc >> (24 - i * 8)) & 255;
}

inline bool decodePrefs(const uint8_t* image, size_t size, Prefs& prefs) {
  if (!image || size != PREFS_IMAGE_SIZE || memcmp(image, "UDP1", 4) != 0
      || image[5] != 0) return false;
  for (uint8_t i = 56; i < 60; ++i) if (image[i] != 0) return false;
  uint32_t crc = 0;
  for (uint8_t i = 0; i < 4; ++i) crc = (crc << 8) | image[60 + i];
  if (crc != prefsChecksum(image, PREFS_IMAGE_SIZE - 4)) return false;
  Prefs candidate;
  candidate.enabled = image[4];
  candidate.port = static_cast<uint16_t>((image[6] << 8) | image[7]);
  for (uint8_t i = 0; i < MAX_PEERS; ++i) {
    memcpy(candidate.peers[i].ip, image + 8 + i * 6, 4);
    candidate.peers[i].port = static_cast<uint16_t>(
        (image[12 + i * 6] << 8) | image[13 + i * 6]);
  }
  if (!validPrefs(candidate)) return false;
  prefs = candidate;
  return true;
}

}}}  // namespace mesh::bridge::udp
