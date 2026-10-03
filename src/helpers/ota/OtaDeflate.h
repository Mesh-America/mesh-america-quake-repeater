#pragma once

#include <stdint.h>
#include "OtaDeflateConfig.h"

namespace mesh {
namespace ota {

// Full raw RFC1951 transport decoder (stored, fixed-Huffman, and dynamic-Huffman blocks).
// `dst_cap` is the exact expected logical block length, not merely spare capacity. Success
// requires exact output and exact whole-byte input consumption; malformed/truncated streams,
// output overflow, and trailing bytes fail closed.
bool ota_transport_inflate(void* context, const uint8_t* src, uint16_t src_len,
                           uint8_t* dst, uint16_t dst_cap, uint16_t* dst_len);

#if MESHCORE_OTA_DEVICE_DEFLATE
// Compact fixed-Huffman raw RFC1951 encoder; independent blocks of at most
// 2048 bytes, with disjoint input/output. Returns false/zero length on invalid
// arguments, OOM, output overflow, or no size saving, selecting raw OTA DATA.
// 512 uint16_t hash offsets (1024 bytes) are allocated only during the call.
// No shared state: repeated/reordered/concurrent blocks encode identically.
bool ota_transport_deflate(void* context, const uint8_t* src, uint16_t src_len,
                           uint8_t* dst, uint16_t dst_cap, uint16_t* dst_len);
#endif

} // namespace ota
} // namespace mesh
