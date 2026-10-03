#pragma once

// Device-side compression is useful only where peers can install full own-images.
// Source-only Companions retain the host's stronger precompressed-block path;
// internal-only nRF52 receivers do not pay the encoder's flash or RAM cost.
#ifndef MESHCORE_OTA_DEVICE_DEFLATE
#if defined(OTA_TRANSPORT_DEFLATE_TEST)
#define MESHCORE_OTA_DEVICE_DEFLATE 1
#else
#define MESHCORE_OTA_DEVICE_DEFLATE 0
#endif
#endif

// Production's shared pre-script positively qualifies the effective source
// filter and platform/storage, and supplies this flag to EVERY translation
// unit. Without qualification the default stays off, including Companions,
// receiver-only targets, unknown roles and custom recipes missing the hook.

// Independent 2 KiB blocks need only 16-bit input offsets. 512 entries use
// 1024 bytes, allocated for one encode call and released before radio TX.
#ifndef MESHCORE_OTA_DEFLATE_HASH_BITS
#define MESHCORE_OTA_DEFLATE_HASH_BITS 9
#endif
#if MESHCORE_OTA_DEFLATE_HASH_BITS < 7 || MESHCORE_OTA_DEFLATE_HASH_BITS > 10
#error "Device DEFLATE hash must have 128..1024 entries"
#endif
#define MESHCORE_OTA_DEFLATE_BLOCK_MAX 2048u
