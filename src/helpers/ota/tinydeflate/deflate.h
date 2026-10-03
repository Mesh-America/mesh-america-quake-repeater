#ifndef MESHCORE_TINY_DEFLATE_H
#define MESHCORE_TINY_DEFLATE_H

#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

// Modified uzlib compressor: bounded caller-owned raw RFC1951 output only.
// Returns zero on OOM/output overflow/invalid parameters. No decoder, container
// headers, checksum, persistent dictionary, or dynamic-Huffman tree is included.
uint16_t meshcore_deflate_raw(const uint8_t* src, uint16_t src_len,
                             uint8_t* dst, uint16_t dst_cap);

#ifdef __cplusplus
}
#endif
#endif
