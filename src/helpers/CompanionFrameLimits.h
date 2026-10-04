#pragma once

#include <stddef.h>

#define MAX_FRAME_SIZE 176  // +4 for transport codes (region scoping)

namespace mesh {

// Binary responses add an opcode and reserved byte to decrypted radio data.
// A direct datagram exposes its zero padding, so reserve whole cipher blocks
// that fit the host frame rather than counting only unpadded ACL entries.
constexpr size_t companionBinaryPlaintextCapacity(size_t cipher_block_size) {
  return cipher_block_size > 0
      ? ((MAX_FRAME_SIZE - 2) / cipher_block_size) * cipher_block_size : 0;
}

}  // namespace mesh
