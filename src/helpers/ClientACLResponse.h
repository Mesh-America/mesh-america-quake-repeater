#pragma once

#include <Packet.h>
#include "DatagramPayloadLimits.h"

namespace mesh {

// Match createDatagram() and createPathReturn() admission limits. A flood
// request returns its observed path inside the encrypted response, so those
// bytes must also be reserved before adding legacy seven-byte ACL entries.
static constexpr size_t CLIENT_ACL_DIRECT_REPLY_CAPACITY =
    DatagramPayloadLimits::maxPlaintext(
        MAX_PACKET_PAYLOAD, CIPHER_MAC_SIZE, CIPHER_BLOCK_SIZE);

inline size_t clientACLReplyCapacity(bool flood, uint8_t path_len) {
  if (!Packet::isValidPathLen(path_len)) return 0;
  if (!flood) return CLIENT_ACL_DIRECT_REPLY_CAPACITY;
  const size_t path_bytes = (path_len & 63) * ((path_len >> 6) + 1);
  // createPathReturn(): path_bytes + extra_len + 5 <=
  // MAX_PACKET_PAYLOAD - 2 - CIPHER_BLOCK_SIZE.
  const size_t fixed_bytes = 2 + CIPHER_BLOCK_SIZE + 5;
  return path_bytes + fixed_bytes <= MAX_PACKET_PAYLOAD
      ? MAX_PACKET_PAYLOAD - path_bytes - fixed_bytes : 0;
}

}  // namespace mesh
