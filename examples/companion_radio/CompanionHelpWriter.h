#pragma once

#include <stddef.h>
#include <stdint.h>

class Stream;

namespace mesh { namespace companion {

// The implementation is isolated in one selected C++17 packing source.
size_t writePackedCompanionHelp(Stream& output);

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

#if __cplusplus >= 201703L
namespace help_packing {

// ASCII literals retain bit 7 clear. Two-byte references encode a 3..18 byte
// match at distance 1..2048. Only the final packed bytes survive evaluation;
// the hash chains and original text occupy no runtime storage.
#if defined(STM32_PLATFORM) && defined(STM32WLxx)
// Small STM32WL Companions retain their 1 KiB minimum stack allowance. A
// smaller history preserves every help byte without adding a 2 KiB frame.
constexpr size_t WindowSize = 256;
#else
constexpr size_t WindowSize = 2048;
#endif
constexpr size_t MaximumMatch = 18;
constexpr uint8_t hash(const char* text) {
  return static_cast<uint8_t>((static_cast<uint8_t>(text[0]) * 31u +
      static_cast<uint8_t>(text[1])) * 31u + static_cast<uint8_t>(text[2]));
}

template<size_t N, typename Emit>
constexpr size_t encode(const char (&text)[N], Emit emit) {
  static_assert(N <= 65535, "Compile-time help offsets use 16 bits");
  uint16_t heads[256] = {}, previous[N] = {};
  size_t position = 0, packed = 0;
  while (position + 1 < N) {
    const size_t remaining = N - position - 1;
    const size_t maximum = remaining < MaximumMatch ? remaining : MaximumMatch;
    size_t best = 0, distance = 0;
    if (remaining >= 3) {
      uint16_t link = heads[hash(text + position)];
      while (link) {
        const size_t candidate = link - 1;
        const size_t back = position - candidate;
        if (back > WindowSize) break;
        size_t match = 0;
        while (match < maximum && text[candidate + match] == text[position + match]) ++match;
        if (match > best) {
          best = match;
          distance = back;
          if (best == maximum) break;
        }
        link = previous[candidate];
      }
    }
    const size_t step = best >= 3 ? best : 1;
    if (best >= 3) {
      emit(static_cast<uint8_t>(0x80 | ((best - 3) << 3) | ((distance - 1) >> 8)));
      emit(static_cast<uint8_t>(distance - 1));
      packed += 2;
    } else {
      emit(static_cast<uint8_t>(text[position]));
      ++packed;
    }
    // Index skipped match bytes too, preserving greedy longest-match choices.
    for (size_t end = position + step; position < end; ++position) {
      if (position + 3 >= N) continue;
      const uint8_t bucket = hash(text + position);
      previous[position] = heads[bucket];
      heads[bucket] = static_cast<uint16_t>(position + 1);
    }
  }
  return packed;
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
  return help_packing::encode(text, [](uint8_t) constexpr {});
}

template<size_t N> struct PackedHelp {
  static_assert(N > 0, "A help image must contain text");
  uint8_t bytes[N] = {};
};

template<size_t PackedSize, size_t N>
constexpr PackedHelp<PackedSize> packHelp(const char (&text)[N]) {
  PackedHelp<PackedSize> result{};
  size_t packed = 0;
  help_packing::encode(text, [&](uint8_t byte) constexpr { result.bytes[packed++] = byte; });
  return result;
}

template<typename Output>
size_t writePackedHelp(Output& output, const uint8_t* packed, size_t length) {
  if (!packed) return 0;
  uint8_t history[help_packing::WindowSize];
  size_t position = 0, produced = 0, written = 0;
  size_t distance = 0, remaining = 0;
  while (position < length || remaining) {
    char chunk[64];
    size_t used = 0;
    while (used < sizeof(chunk) && (position < length || remaining)) {
      uint8_t next;
      if (remaining) {
        next = history[(produced - distance) & (help_packing::WindowSize - 1)];
        --remaining;
      } else {
        next = packed[position++];
        if (next & 0x80) {
          if (position == length) return written;
          distance = ((static_cast<size_t>(next & 7) << 8) | packed[position++]) + 1;
          remaining = ((next >> 3) & 15) + 3;
          if (distance > produced || distance > help_packing::WindowSize) return written;
          continue;
        }
      }
      history[produced++ & (help_packing::WindowSize - 1)] = next;
      chunk[used++] = static_cast<char>(next);
    }
    const size_t accepted = writeHelpChunks(output, chunk, used);
    written += accepted;
    if (accepted != used) break;
  }
  return written;
}

#endif // C++17 constant packing and streaming decoder

} } // namespace mesh::companion
