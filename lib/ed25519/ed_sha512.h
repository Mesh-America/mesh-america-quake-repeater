#ifndef ED25519_SHA512_H
#define ED25519_SHA512_H

#include <stddef.h>

#include "fixedint.h"

#ifndef ED25519_USE_CRYPTO_SHA512
#define ED25519_USE_CRYPTO_SHA512 0
#endif

#if ED25519_USE_CRYPTO_SHA512
/* C-owned, aligned storage for the optional C++ SHA512 implementation. */
typedef union sha512_context_ {
    uint64_t alignment;
    unsigned char opaque[256];
} sha512_context;
#else
/* state */
typedef struct sha512_context_ {
    uint64_t  length, state[8];
    size_t curlen;
    unsigned char buf[128];
} sha512_context;
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* A completed context must be initialized again before reuse. */
int sha512_init(sha512_context * md);
int sha512_final(sha512_context * md, unsigned char *out);
int sha512_update(sha512_context * md, const unsigned char *in, size_t inlen);
int sha512(const unsigned char *message, size_t message_len, unsigned char *out);

#ifdef __cplusplus
}
#endif

#endif
