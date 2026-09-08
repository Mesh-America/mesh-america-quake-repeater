#include <cassert>
#include <cstring>
#include <helpers/ContactSecretCache.h>

class NoIoBackend : public mesh::ContactSecretBackend {
public:
  bool readSavedSecret(const uint8_t*, const uint8_t*, uint8_t*) override {
    assert(false && "ESP32 cache misses must not read flash");
    return false;
  }
  bool saveSecret(const uint8_t*, const uint8_t*, const uint8_t*) override {
    assert(false && "ESP32 cache misses must not write flash");
    return false;
  }
};

int main() {
  NoIoBackend backend;
  mesh::ContactSecretCache cache;
  cache.attach(&backend);
  mesh::LocalIdentity self, peer;
  uint8_t seed[32] = {1};
  ed25519_create_keypair(self.pub_key, self.private_key, seed);
  seed[0] = 2;
  ed25519_create_keypair(peer.pub_key, peer.private_key, seed);
  uint8_t expected[32];
  peer.calcSharedSecret(expected, self.pub_key);
  assert(memcmp(cache.get(self, peer.pub_key), expected, 32) == 0);
  assert(memcmp(cache.get(self, peer.pub_key), expected, 32) == 0);
  assert(self.derivations == 1 && cache.ram_hits == 1);
  for (unsigned i = 3; i < 20; ++i) {
    mesh::LocalIdentity other;
    seed[0] = i;
    ed25519_create_keypair(other.pub_key, other.private_key, seed);
    cache.get(self, other.pub_key);
  }
  const unsigned before = self.derivations;
  assert(memcmp(cache.get(self, peer.pub_key), expected, 32) == 0);
  assert(self.derivations == before + 1);
  assert(cache.flash_hits == 0 && cache.save_failures == 0);
  self.private_key[1] ^= 2;
  assert(memcmp(cache.get(self, peer.pub_key), expected, 32) != 0);
  assert(self.derivations == before + 2);
}
