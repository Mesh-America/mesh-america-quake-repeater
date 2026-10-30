#include "ed_sha512.h"

#if ED25519_USE_CRYPTO_SHA512
#include <SHA512.h>
#include <new>

// Share the SHA-512 already used by Crypto's Ed25519 verifier. Contexts remain
// caller-owned; hashing and signing allocate no heap and share no mutable state.
static_assert(sizeof(SHA512) <= sizeof(sha512_context), "SHA512 context capacity");
static_assert(alignof(SHA512) <= alignof(sha512_context), "SHA512 context alignment");

namespace {
SHA512* implementation(sha512_context* context) {
    return reinterpret_cast<SHA512*>(context->opaque);
}
}

extern "C" int sha512_init(sha512_context* context) {
    if (!context) return 1;
    new (context->opaque) SHA512();
    return 0;
}

extern "C" int sha512_update(sha512_context* context, const unsigned char* input,
                              size_t length) {
    if (!context || !input) return 1;
    implementation(context)->SHA512::update(input, length);
    return 0;
}

extern "C" int sha512_final(sha512_context* context, unsigned char* output) {
    if (!context || !output) return 1;
    SHA512* hash = implementation(context);
    hash->SHA512::finalize(output, SHA512::HASH_SIZE);
    hash->SHA512::~SHA512();
    return 0;
}

extern "C" int sha512(const unsigned char* message, size_t length,
                      unsigned char* output) {
    if (!message || !output) return 1;
    sha512_context context;
    sha512_init(&context);
    sha512_update(&context, message, length);
    sha512_final(&context, output);
    return 0;
}
#endif
