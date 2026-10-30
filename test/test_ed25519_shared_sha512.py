"""Exercise both Ed25519 signing hash backends with the real Crypto verifier."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ED25519 = ROOT / "lib/ed25519"
LENGTHS = (0, 1, 63, 64, 111, 112, 127, 128, 129, 239, 240, 255,
           256, 257, 1024, 4097, 16385)

HARNESS = r'''
#include "ed_sha512.h"
#include "ed_25519.h"
#include <Ed25519.h>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#if defined(_WIN32)
#include <RNG.h>
// PE linkers resolve the library's unused key-generation references before
// discarding them. Verification and seeded signing must never call this API.
RNGClass::RNGClass() {}
RNGClass::~RNGClass() {}
void RNGClass::rand(uint8_t*, size_t) { std::abort(); }
RNGClass RNG;
#endif

static void printHex(const unsigned char* bytes, size_t length) {
    for (size_t i = 0; i < length; ++i) printf("%02x", bytes[i]);
    putchar('\n');
}
static const unsigned char* bytes(const std::vector<unsigned char>& data) {
    static const unsigned char empty = 0;
    return data.empty() ? &empty : data.data();
}
static std::vector<unsigned char> message(size_t length, unsigned salt) {
    std::vector<unsigned char> result(length);
    for (size_t i = 0; i < length; ++i) result[i] = (i * 73 + salt) & 255;
    return result;
}
static void decode(unsigned char* output, size_t length, const char* hex) {
    assert(strlen(hex) == length * 2);
    for (size_t i = 0; i < length; ++i) {
        unsigned value;
        assert(sscanf(hex + i * 2, "%2x", &value) == 1);
        output[i] = value;
    }
}
static void verifySignature(unsigned char* signature, const unsigned char* key,
                            const unsigned char* data, size_t length) {
    // Retain the production C++ verification path; do not use the bundled
    // C verifier which Identity deliberately excludes.
    assert(Ed25519::verify(signature, key, data, length));
    for (size_t index : {size_t(0), size_t(17), size_t(32), size_t(63)}) {
        signature[index] ^= 1;
        assert(!Ed25519::verify(signature, key, data, length));
        signature[index] ^= 1;
    }
    std::vector<unsigned char> changed(data, data + length);
    if (changed.empty()) changed.push_back(1); else changed[0] ^= 1;
    assert(!Ed25519::verify(signature, key, bytes(changed), changed.size()));
    unsigned char wrong_key[32];
    memcpy(wrong_key, key, 32); wrong_key[0] ^= 1;
    assert(!Ed25519::verify(signature, wrong_key, data, length));
}
int main() {
    const size_t lengths[] = {@LENGTHS@};
    const size_t chunks[] = {1, 7, 63, 64, 111, 112, 127, 128, 129, 257, 1024};
    unsigned char result[64];
    assert(sha512_init(nullptr) == 1);
    assert(sha512_update(nullptr, result, 0) == 1);
    assert(sha512_final(nullptr, result) == 1);
    assert(sha512(nullptr, 0, result) == 1);
    assert(sha512(result, 0, nullptr) == 1);
    for (size_t length : lengths) {
        const auto first = message(length, 19), second = message(length + 137, 91);
        assert(sha512(bytes(first), first.size(), result) == 0);
        printHex(result, sizeof(result));
        sha512_context contexts[2];
        size_t positions[2] = {}, turn = 0;
        for (auto& context : contexts) {
            assert(sha512_init(&context) == 0);
            assert(sha512_update(&context, nullptr, 0) == 1);
            assert(sha512_final(&context, nullptr) == 1);
            assert(sha512_update(&context, result, 0) == 0);
        }
        while (positions[0] < first.size() || positions[1] < second.size()) {
            for (unsigned i = 0; i < 2; ++i) {
                const auto& data = i ? second : first;
                size_t count = chunks[turn++ % (sizeof(chunks) / sizeof(chunks[0]))];
                if (count > data.size() - positions[i]) count = data.size() - positions[i];
                assert(sha512_update(&contexts[i], bytes(data) + positions[i], count) == 0);
                positions[i] += count;
            }
        }
        for (auto& context : contexts) {
            assert(sha512_final(&context, result) == 0);
            printHex(result, sizeof(result));
            // Restart a completed context and reset an unfinished one. Both
            // must discard the old message without touching another context.
            assert(sha512_init(&context) == 0);
            assert(sha512_update(&context, bytes(second), second.size()) == 0);
            assert(sha512_init(&context) == 0);
            assert(sha512_update(&context, bytes(first), first.size()) == 0);
            assert(sha512_final(&context, result) == 0);
            unsigned char expected[64];
            assert(sha512(bytes(first), first.size(), expected) == 0);
            assert(!memcmp(result, expected, 64));
        }
    }
    struct Vector { const char* seed; const char* key; const char* data; const char* signature; };
    // RFC 8032 section 7.1, tests 1-3.
    // https://www.rfc-editor.org/rfc/rfc8032.html#section-7.1
    const Vector vectors[] = {
        {"9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
         "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"},
        {"4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085"
         "ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"},
        {"c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
         "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
         "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"}
    };
    for (const auto& vector : vectors) {
        unsigned char seed[32], key[32], expected_key[32], secret[64], signature[64], expected[64];
        std::vector<unsigned char> data(strlen(vector.data) / 2);
        decode(seed, 32, vector.seed); decode(expected_key, 32, vector.key);
        decode(expected, 64, vector.signature);
        if (!data.empty()) decode(data.data(), data.size(), vector.data);
        ed25519_create_keypair(key, secret, seed);
        assert(!memcmp(key, expected_key, 32));
        ed25519_sign(signature, bytes(data), data.size(), key, secret);
        assert(!memcmp(signature, expected, 64));
        verifySignature(signature, key, bytes(data), data.size());
    }
    // Cross-backend byte-for-byte comparison covers long, irregular messages
    // and existing expanded private-key storage, beyond the short RFC cases.
    for (size_t length : lengths) {
        unsigned char seed[32], key[32], secret[64], signature[64];
        const auto data = message(length, 37);
        for (unsigned i = 0; i < 32; ++i) seed[i] = (length + i * 17) & 255;
        ed25519_create_keypair(key, secret, seed);
        ed25519_sign(signature, bytes(data), data.size(), key, secret);
        verifySignature(signature, key, bytes(data), data.size());
        printHex(key, 32); printHex(secret, 64); printHex(signature, 64);
    }
    puts("Shared SHA512 and RFC8032 checks passed");
}
'''


class SharedSHA512Test(unittest.TestCase):
    def test_c_api_hashes_and_signatures_match_original_and_rfc8032(self):
        compiler = shutil.which("gcc")
        cpp = shutil.which("g++")
        self.assertIsNotNone(compiler, "C compiler required")
        self.assertIsNotNone(cpp, "C++ compiler required")
        override = os.environ.get("MESHCORE_CRYPTO_DIR")
        candidates = [Path(override)] if override else sorted((ROOT / ".pio/libdeps").glob("*/Crypto"))
        names = ("SHA512.cpp", "Hash.cpp", "Crypto.cpp", "Ed25519.cpp", "Curve25519.cpp",
                 "BigNumberUtil.cpp")
        crypto = next((path for path in candidates if all((path / name).is_file() for name in names)), None)
        self.assertIsNotNone(crypto, "Install rweather/Crypto or set MESHCORE_CRYPTO_DIR (no crypto mocks)")
        flags = ["-O1", "-g", "-Wall", "-Wextra", "-Werror", "-DHOST_BUILD=1",
                 "-DED25519_NO_SEED=1", "-DED25519_SMALL_BASE=1",
                 "-DED25519_COMPACT_SHA512=1", "-DED25519_COMPACT_SCALAR=1",
                 "-DED25519_COMPACT_FIELD=1", "-ffunction-sections", "-fdata-sections",
                 "-I" + str(ED25519), "-I" + str(crypto)]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        with tempfile.TemporaryDirectory(prefix="ed25519-shared-sha512-") as directory:
            work = Path(directory)
            if os.name == "nt":
                # Crypto's HOST_BUILD expects the POSIX byte-order header.
                # MinGW supplies the same conversions as compiler intrinsics.
                endian = "#pragma once\n#include <stdint.h>\n"
                endian += "static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, \"host byte order\");\n"
                for bits in (16, 32, 64):
                    for name in (f"htobe{bits}", f"be{bits}toh"):
                        endian += f"static inline uint{bits}_t {name}(uint{bits}_t n) {{ return __builtin_bswap{bits}(n); }}\n"
                    for name in (f"htole{bits}", f"le{bits}toh"):
                        endian += f"static inline uint{bits}_t {name}(uint{bits}_t n) {{ return n; }}\n"
                (work / "endian.h").write_text(endian)
                flags += ["-I" + str(work)]
            harness = work / "harness.cpp"
            source = HARNESS.replace("@LENGTHS@", ",".join(map(str, LENGTHS)))
            harness.write_text(source)
            outputs = []
            for shared in (0, 1):
                with self.subTest(shared=shared):
                    build_flags = flags + [f"-DED25519_USE_CRYPTO_SHA512={shared}"]
                    objects = []
                    for name in ("fe.c", "ge.c", "keypair.c", "sc.c", "sha512.c", "sign.c"):
                        obj = work / (name + f"-{shared}.o")
                        # Legacy ref10 carries shift negative signed values.
                        # Keep ASan and all other UBSan checks on those files;
                        # the new adapter and both hash implementations retain
                        # the complete sanitizer set.
                        legacy = ["-fno-sanitize=shift"] if os.name != "nt" and name in ("fe.c", "ge.c") else []
                        built = subprocess.run([compiler, "-std=c99", *build_flags, *legacy, "-c", str(ED25519 / name),
                                                "-o", str(obj)], capture_output=True, text=True, timeout=60)
                        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                        objects.append(str(obj))
                    binary = work / f"shared-{shared}"
                    built = subprocess.run([cpp, "-std=c++11", *build_flags, str(harness),
                                            str(ED25519 / "ed_sha512_crypto.cpp"),
                                            *[str(crypto / name) for name in names], *objects,
                                            "-Wl,--gc-sections", "-o", str(binary)],
                                           capture_output=True, text=True, timeout=90)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    lines = run.stdout.splitlines()
                    expected = []
                    for length in LENGTHS:
                        first = bytes((i * 73 + 19) & 255 for i in range(length))
                        second = bytes((i * 73 + 91) & 255 for i in range(length + 137))
                        expected += [hashlib.sha512(first).hexdigest()] * 2
                        expected += [hashlib.sha512(second).hexdigest()]
                    self.assertEqual(lines[:len(expected)], expected)
                    self.assertEqual(lines[-1], "Shared SHA512 and RFC8032 checks passed")
                    outputs.append(lines)
            self.assertEqual(len(outputs), 2)
            self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
