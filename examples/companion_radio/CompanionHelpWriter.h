#pragma once

#include <stddef.h>
#include <stdint.h>

namespace mesh { namespace companion {

// Native USB accepts bounded producer writes. Honor partial progress, and stop
// if the sink cannot accept another byte rather than spinning on a closed host.
template<typename Output>
size_t writeHelpChunks(Output& output, const char* text, size_t length) {
  if (!text) return 0;
  size_t written = 0;
  while (written < length) {
    const size_t remaining = length - written;
    const size_t chunk = remaining > 256 ? 256 : remaining;
    const size_t accepted = output.write(
        reinterpret_cast<const uint8_t*>(text) + written, chunk);
    if (accepted == 0 || accepted > chunk) break;
    written += accepted;
  }
  return written;
}

namespace help_packing {

// Help is ASCII. Bytes 0x80..0x8f encode these common fragments; the original
// text exists only during constant evaluation, never alongside the packed data.
constexpr size_t TokenCount = 16;
constexpr char Dictionary[] =
    "  get/set \0" "  get \0" "  set \0" "get/set \0"
    "bluetooth.\0" "pwrmgt.\0" "radio.\0" "default\0"
    "preamble\0" "on|off\0" " (saved; \0" "  \0"
    "get \0" "set \0" "\r\n\0" " / \0";

struct TokenOffsets { uint8_t value[TokenCount + 1] = {}; };
constexpr TokenOffsets tokenOffsets() {
  TokenOffsets result{};
  size_t offset = 0;
  for (size_t token = 0; token < TokenCount; ++token) {
    result.value[token] = static_cast<uint8_t>(offset);
    while (Dictionary[offset]) ++offset;
    ++offset;
  }
  result.value[TokenCount] = static_cast<uint8_t>(offset);
  return result;
}
static_assert(sizeof(Dictionary) < 256, "Help dictionary offsets need one byte");
constexpr TokenOffsets Offsets = tokenOffsets();
constexpr size_t tokenLength(size_t token) {
  return Offsets.value[token + 1] - Offsets.value[token] - 1;
}
constexpr size_t matchToken(const char* text, size_t remaining) {
  for (size_t token = 0; token < TokenCount; ++token) {
    const char* fragment = Dictionary + Offsets.value[token];
    const size_t length = tokenLength(token);
    if (length > remaining || *text != *fragment) continue;
    size_t i = 1;
    while (i < length && text[i] == fragment[i]) ++i;
    if (i == length) return token;
  }
  return TokenCount;
}

} // namespace help_packing

template<size_t N>
constexpr bool validHelpText(const char (&text)[N]) {
  if (text[N - 1] != 0) return false;
  for (size_t i = 0; i + 1 < N; ++i) {
    if (text[i] == 0 || static_cast<uint8_t>(text[i]) >= 0x80) return false;
  }
  return true;
}

template<size_t N>
constexpr size_t packedHelpSize(const char (&text)[N]) {
  size_t packed = 0;
  for (size_t i = 0; i + 1 < N; ++packed) {
    const size_t token = help_packing::matchToken(text + i, N - i - 1);
    i += token < help_packing::TokenCount ? help_packing::tokenLength(token) : 1;
  }
  return packed;
}

template<size_t N> struct PackedHelp {
  static_assert(N > 0, "A help image must contain text");
  uint8_t bytes[N] = {};
};

template<size_t PackedSize, size_t N>
constexpr PackedHelp<PackedSize> packHelp(const char (&text)[N]) {
  PackedHelp<PackedSize> result{};
  size_t packed = 0;
  for (size_t i = 0; i + 1 < N;) {
    const size_t token = help_packing::matchToken(text + i, N - i - 1);
    if (token < help_packing::TokenCount) {
      result.bytes[packed++] = static_cast<uint8_t>(0x80 + token);
      i += help_packing::tokenLength(token);
    } else {
      result.bytes[packed++] = static_cast<uint8_t>(text[i++]);
    }
  }
  return result;
}

template<typename Output>
size_t writePackedHelp(Output& output, const uint8_t* packed, size_t length) {
  if (!packed) return 0;
  size_t position = 0, written = 0;
  const char* expansion = nullptr;
  while (position < length || expansion) {
    char chunk[64];
    size_t used = 0;
    while (used < sizeof(chunk) && (position < length || expansion)) {
      if (expansion) {
        const char next = *expansion++;
        if (next) chunk[used++] = next;
        else expansion = nullptr;
      } else {
        const uint8_t next = packed[position++];
        if (next >= 0x80) {
          const size_t token = next - 0x80;
          if (token >= help_packing::TokenCount) return written;
          expansion = help_packing::Dictionary + help_packing::Offsets.value[token];
        } else {
          chunk[used++] = static_cast<char>(next);
        }
      }
    }
    const size_t accepted = writeHelpChunks(output, chunk, used);
    written += accepted;
    if (accepted != used) break;
  }
  return written;
}

} } // namespace mesh::companion
