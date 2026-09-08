#pragma once

#include <Arduino.h>
#include "ContactCachePolicy.h"
#include <Identity.h>
#include <Utils.h>
#include <stdint.h>
#include <string.h>

namespace mesh {

class ContactSecretBackend {
public:
  virtual bool readSavedSecret(const uint8_t peer[32], const uint8_t identity[32],
                               uint8_t secret[32]) = 0;
  virtual bool saveSecret(const uint8_t peer[32], const uint8_t identity[32],
                          const uint8_t secret[32]) = 0;
};

class ContactSecretCache {
  struct Entry {
    uint8_t peer[32] = {};
    uint8_t secret[32] = {};
    uint8_t age = 0;
    bool valid = false;
  } _entries[16];
  uint8_t _identity[PRV_KEY_SIZE + PUB_KEY_SIZE] = {};
#if MESH_CONTACT_SECRET_FLASH_CACHE
  uint8_t _identity_hash[32] = {};
#endif
  bool _has_identity = false;
#if MESH_CONTACT_SECRET_FLASH_CACHE
  ContactSecretBackend* _backend = nullptr;
#endif
public:
  uint32_t ram_hits = 0;
  uint32_t flash_hits = 0;
  uint32_t calculations = 0;
  uint32_t save_failures = 0;
  uint32_t last_flash_read_us = 0;
  uint32_t last_calculation_us = 0;

  void attach(ContactSecretBackend* backend) {
#if MESH_CONTACT_SECRET_FLASH_CACHE
    _backend = backend;
#else
    (void)backend;
#endif
  }
  const uint8_t* get(const LocalIdentity& self, const uint8_t peer[32]) {
    uint8_t identity[sizeof(_identity)];
    self.writeTo(identity, sizeof(identity));
    // Compare the complete key pair, including private material. An identity
    // import must invalidate RAM and flash lookups even if its public bytes
    // happen to be unchanged. Only a SHA-256 fingerprint is stored with a page.
    if (!_has_identity || memcmp(identity, _identity, sizeof(identity)) != 0) {
      for (auto& e : _entries) { memset(e.secret, 0, sizeof(e.secret)); e.valid = false; }
      memcpy(_identity, identity, sizeof(identity));
#if MESH_CONTACT_SECRET_FLASH_CACHE
      Utils::sha256(_identity_hash, sizeof(_identity_hash), identity, sizeof(identity));
#endif
      _has_identity = true;
    }
    int chosen = -1;
    bool hit = false;
    for (int i = 0; i < 16; ++i) {
      if (_entries[i].valid && memcmp(_entries[i].peer, peer, 32) == 0) {
        chosen = i;
        hit = true;
        break;
      }
      if (chosen < 0 || !_entries[i].valid ||
          (_entries[chosen].valid && _entries[i].age > _entries[chosen].age)) chosen = i;
    }
    Entry& e = _entries[chosen];
    if (hit) {
      ++ram_hits;
    } else {
      e.valid = false;
      memcpy(e.peer, peer, 32);
#if MESH_CONTACT_SECRET_FLASH_CACHE
      const uint32_t started = micros();
      if (_backend && _backend->readSavedSecret(peer, _identity_hash, e.secret)) {
        last_flash_read_us = micros() - started;
        ++flash_hits;
      } else
#endif
      {
        const uint32_t started = micros();
        self.calcSharedSecret(e.secret, peer);
        last_calculation_us = micros() - started;
        ++calculations;
#if MESH_CONTACT_SECRET_FLASH_CACHE
        if (_backend && !_backend->saveSecret(peer, _identity_hash, e.secret)) ++save_failures;
#endif
      }
      e.valid = true;
    }
    for (auto& other : _entries) if (other.valid && other.age < 16) ++other.age;
    e.age = 0;
    return e.secret;
  }
};

ContactSecretCache& contactSecretCache();

} // namespace mesh
