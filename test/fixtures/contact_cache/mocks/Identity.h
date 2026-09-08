#pragma once
#include "Utils.h"
#include <ed_25519.h>
namespace mesh {
class Identity {
public:
  uint8_t pub_key[32] = {};
  Identity() = default;
  explicit Identity(const uint8_t* key) { memcpy(pub_key, key, 32); }
};
class LocalIdentity : public Identity {
public:
  uint8_t private_key[64] = {};
  mutable unsigned derivations = 0;
  size_t writeTo(uint8_t* out, size_t size) const {
    if (size < 96) return 0;
    memcpy(out, private_key, 64);
    memcpy(out + 64, pub_key, 32);
    return 96;
  }
  void calcSharedSecret(uint8_t* out, const uint8_t* peer) const {
    ++derivations;
    ed25519_key_exchange(out, peer, private_key);
  }
};
}
