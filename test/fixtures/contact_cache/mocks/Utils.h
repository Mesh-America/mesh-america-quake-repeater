#pragma once
#include <stdint.h>
#include <stddef.h>
#include <openssl/sha.h>
#include <cstring>
#define PUB_KEY_SIZE 32
#define PRV_KEY_SIZE 64
namespace mesh {
class Utils {
public:
  static void sha256(uint8_t* out, size_t size, const uint8_t* data, int length) {
    uint8_t digest[32];
    SHA256(data, length, digest);
    memcpy(out, digest, size);
  }
};
}

