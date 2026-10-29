#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "../ota/tinf/tinf.h"

namespace mesh { namespace bible {

static constexpr size_t kBlockSize = 4096;
static constexpr uint16_t kVerseCount = 879;
static constexpr uint8_t kChapterVerses[] = {
  51, 25, 36, 54, 47, 71, 53, 59, 41, 42, 57,
  50, 38, 31, 27, 33, 26, 40, 42, 31, 25
};

struct Reference { uint8_t chapter; uint8_t verse; };
enum class ParseResult { NoMatch, Invalid, Valid };
template <typename Offset> struct BlockIndexT {
  Offset offset;
  uint16_t packed;
  uint16_t plain;
  uint16_t first_verse;
};
template <typename Offset> struct CorpusT {
  const char* translation;
  const char* attribution;
  const uint8_t* data;
  uint32_t data_size;
  const BlockIndexT<Offset>* blocks;
  uint16_t block_count;
  uint16_t verse_count;
};
// Keep the original plain corpus aggregate and its seven-field initializer.
// Token metadata is static flash data; no decoded block or heap is retained.
template <typename Offset> struct TokenCorpusT : CorpusT<Offset> {
  const uint8_t* words;
  uint16_t words_size;
  const uint16_t* word_offsets;
  uint16_t word_count;

  constexpr TokenCorpusT(const char* translation, const char* attribution,
      const uint8_t* data, uint32_t data_size, const BlockIndexT<Offset>* blocks,
      uint16_t block_count, uint16_t verse_count, const uint8_t* words,
      uint16_t words_size, const uint16_t* word_offsets, uint16_t word_count)
      : CorpusT<Offset>{translation, attribution, data, data_size, blocks,
                        block_count, verse_count},
        words(words), words_size(words_size), word_offsets(word_offsets),
        word_count(word_count) {}
};
// Keep the original general-purpose types available. Generated corpora select
// a narrower offset only when every block start fits, without a runtime branch.
using BlockIndex = BlockIndexT<uint32_t>;
using Corpus = CorpusT<uint32_t>;
enum class LookupResult { Found, Missing, Invalid, Corrupt };

inline bool space(char c) { return c == ' ' || c == '\t'; }
inline void skipSpace(const char*& p) { while (space(*p)) ++p; }
inline char lower(char c) { return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c; }

inline bool token(const char*& p, const char* word) {
  const char* q = p;
  for (; *word; ++word, ++q) {
    if (lower(*q) != *word) return false;
  }
  if (*q && !space(*q)) return false;
  p = q;
  return true;
}

inline bool number(const char*& p, uint8_t& result) {
  unsigned value = 0;
  const char* start = p;
  while (*p >= '0' && *p <= '9') {
    if (p - start >= 2) return false;
    value = value * 10 + static_cast<unsigned>(*p++ - '0');
  }
  if (p == start || value == 0) return false;
  result = static_cast<uint8_t>(value);
  return true;
}

inline bool verseNumber(Reference ref, uint16_t& index) {
  if (ref.chapter == 0 || ref.chapter > sizeof(kChapterVerses) ||
      ref.verse == 0 || ref.verse > kChapterVerses[ref.chapter - 1]) return false;
  index = ref.verse - 1;
  for (unsigned c = 0; c + 1 < ref.chapter; ++c) index += kChapterVerses[c];
  return true;
}

inline ParseResult parse(const char* command, Reference& ref) {
  if (!command) return ParseResult::NoMatch;
  skipSpace(command);
  if (!token(command, "get")) return ParseResult::NoMatch;
  skipSpace(command);
  if (!token(command, "reader")) return ParseResult::NoMatch;
  skipSpace(command);
  if (!number(command, ref.chapter) || *command != ':') return ParseResult::Invalid;
  ++command;
  if (!number(command, ref.verse)) return ParseResult::Invalid;
  skipSpace(command);
  uint16_t unused;
  return *command == 0 && verseNumber(ref, unused)
      ? ParseResult::Valid : ParseResult::Invalid;
}

// One independently compressed block is decoded on demand. Const tables/data
// stay in memory-mapped flash on both target families; there is no heap/cache.
template <typename Offset>
inline LookupResult lookup(const CorpusT<Offset>& corpus, Reference ref,
                           char* scratch, size_t capacity, const char*& text,
                           size_t* decoded_size = nullptr) {
  text = nullptr;
  if (decoded_size) *decoded_size = 0;
  uint16_t index;
  if (!verseNumber(ref, index)) return LookupResult::Invalid;
  if (!scratch || capacity < kBlockSize || !corpus.data || !corpus.blocks ||
      corpus.block_count == 0 || corpus.verse_count != kVerseCount ||
      corpus.blocks[0].first_verse != 0) return LookupResult::Corrupt;
  // Index only the start of each block. The few verse boundaries inside it
  // are found by scanning NUL separators, saving a per-verse flash table.
  unsigned block_index = 0;
  while (block_index + 1 < corpus.block_count &&
         corpus.blocks[block_index + 1].first_verse <= index) ++block_index;
  const BlockIndexT<Offset> block = corpus.blocks[block_index];
  if (block.plain == 0 || block.plain > kBlockSize || block.packed == 0 ||
      block.offset > corpus.data_size || block.packed > corpus.data_size - block.offset ||
      block.first_verse > index) return LookupResult::Corrupt;
  unsigned int produced = block.plain;
  if (tinf_uncompress_exact(scratch, &produced, corpus.data + block.offset,
                            block.packed) != TINF_OK || produced != block.plain) {
    return LookupResult::Corrupt;
  }
  if (decoded_size) *decoded_size = produced;
  const char* current = scratch;
  const char* end = scratch + produced;
  for (unsigned v = block.first_verse; v <= index; ++v) {
    const char* terminator = static_cast<const char*>(memchr(current, 0, end - current));
    if (!terminator) return LookupResult::Corrupt;
    if (v == index) {
      if (terminator == current) return LookupResult::Missing;
      text = current;
      break;
    }
    current = terminator + 1;
  }
  return LookupResult::Found;
}

// Expand only the selected verse after its token block in the same 4 KiB
// scratch. The packer reserves this headroom for every tokenized verse.
template <typename Offset>
inline LookupResult lookup(const TokenCorpusT<Offset>& corpus, Reference ref,
                           char* scratch, size_t capacity, const char*& text) {
  size_t produced;
  const LookupResult result = lookup(static_cast<const CorpusT<Offset>&>(corpus),
                                    ref, scratch, capacity, text, &produced);
  if (result != LookupResult::Found) return result;
  const uint8_t* encoded = reinterpret_cast<const uint8_t*>(text);
  text = nullptr;
  if (!corpus.words || !corpus.word_offsets || corpus.word_count == 0
      || corpus.word_count > 128 || corpus.words_size == 0
      || corpus.word_offsets[0] != 0
      || corpus.word_offsets[corpus.word_count] != corpus.words_size)
    return LookupResult::Corrupt;
  bool tokenized = false;
  for (const uint8_t* p = encoded; *p; ++p) {
    if (*p < 32 || *p == 127) return LookupResult::Corrupt;
    if (*p >= 128) tokenized = true;
  }
  // Literal fallback retains the original maximum-length verse allowance.
  if (!tokenized) {
    text = reinterpret_cast<const char*>(encoded);
    return LookupResult::Found;
  }
  char* output = scratch + produced;
  size_t available = kBlockSize - produced;
  char* dest = output;
  for (; *encoded; ++encoded) {
    const uint8_t* word = encoded;
    size_t length = 1;
    if (*encoded >= 128) {
      const unsigned index = *encoded - 128;
      if (index >= corpus.word_count) return LookupResult::Corrupt;
      const uint16_t start = corpus.word_offsets[index];
      const uint16_t end = corpus.word_offsets[index + 1];
      if (start >= end || end > corpus.words_size) return LookupResult::Corrupt;
      word = corpus.words + start;
      length = end - start;
    }
    if (length >= available) return LookupResult::Corrupt; // Retain the NUL.
    for (size_t i = 0; i < length; ++i) {
      if (word[i] < 32 || word[i] >= 127) return LookupResult::Corrupt;
      *dest++ = static_cast<char>(word[i]);
    }
    available -= length;
  }
  *dest = 0;
  text = output;
  return LookupResult::Found;
}

}} // namespace mesh::bible
