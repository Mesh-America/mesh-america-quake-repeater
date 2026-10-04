#include "CompanionReader.h"

#if COMPANION_FEATURE_READER
#include <Arduino.h>
#include "bible/ReaderLookup.h"

#include "bible/ReaderData.generated.h"

namespace mesh {
bible::LookupResult readReaderVerse(bible::Reference ref, char* scratch,
                                 size_t capacity, const char*& text) {
  return bible::lookup(bible::generated::readerCorpus, ref, scratch, capacity, text);
}

namespace {

constexpr size_t kReplyPageTextBytes = 100;

bible::ParseResult parseReaderRequest(const char* command, bible::Reference& ref,
                                     uint8_t& page) {
  page = 0; // No page argument keeps text terminals' full-verse behavior.
  if (!command) return bible::ParseResult::NoMatch;
  bible::skipSpace(command);
  if (!bible::token(command, "get")) return bible::ParseResult::NoMatch;
  bible::skipSpace(command);
  if (!bible::token(command, "reader")) return bible::ParseResult::NoMatch;
  bible::skipSpace(command);
  if (!bible::number(command, ref.chapter) || *command != ':') {
    return bible::ParseResult::Invalid;
  }
  ++command;
  if (!bible::number(command, ref.verse)) return bible::ParseResult::Invalid;
  uint16_t unused;
  if (!bible::verseNumber(ref, unused)) return bible::ParseResult::Invalid;
  if (*command) {
    if (!bible::space(*command)) return bible::ParseResult::Invalid;
    bible::skipSpace(command);
    if (*command && !bible::number(command, page)) return bible::ParseResult::Invalid;
    bible::skipSpace(command);
  }
  return *command == 0 ? bible::ParseResult::Valid : bible::ParseResult::Invalid;
}

size_t nextReplyPage(const char* text, size_t start, size_t length) {
  size_t count = length - start;
  if (count > kReplyPageTextBytes) {
    count = kReplyPageTextBytes;
    // Keep the separating space in this page, so following every page
    // reconstructs the supplied verse exactly without lost or repeated words.
    for (size_t n = count; n > 0; --n) {
      if (text[start + n - 1] == ' ') {
        count = n;
        break;
      }
    }
  }
  return start + count;
}

void formatVerseReply(bible::Reference ref, uint8_t page, const char* text,
                      char* reply, size_t capacity) {
  char header[40];
  snprintf(header, sizeof(header), "Reader %u:%u (WEB)\n",
           static_cast<unsigned>(ref.chapter), static_cast<unsigned>(ref.verse));
  const size_t length = strlen(text);
  const size_t header_len = strlen(header);
  if (header_len + length < capacity) {
    if (page != 1) {
      snprintf(reply, capacity, "ERROR: Reader page must be 1-1");
    } else {
      memcpy(reply, header, header_len);
      memcpy(reply + header_len, text, length + 1);
    }
    return;
  }

  unsigned parts = 0;
  size_t start = 0, end = 0;
  for (size_t offset = 0; offset < length;) {
    const size_t next = nextReplyPage(text, offset, length);
    if (++parts == page) {
      start = offset;
      end = next;
    }
    offset = next;
  }
  if (page > parts) {
    snprintf(reply, capacity, "ERROR: Reader page must be 1-%u", parts);
    return;
  }
  snprintf(header, sizeof(header), "Reader %u:%u [%u/%u]\n",
           static_cast<unsigned>(ref.chapter), static_cast<unsigned>(ref.verse),
           static_cast<unsigned>(page), parts);
  char next_command[48] = {};
  if (page < parts) {
    snprintf(next_command, sizeof(next_command), "\nNext: get reader %u:%u %u",
             static_cast<unsigned>(ref.chapter), static_cast<unsigned>(ref.verse),
             static_cast<unsigned>(page + 1));
  }
  const size_t prefix_len = strlen(header);
  const size_t text_len = end - start;
  const size_t suffix_len = strlen(next_command);
  if (prefix_len + text_len + suffix_len >= capacity) {
    snprintf(reply, capacity, "ERROR: Reader reply buffer too small");
    return;
  }
  memcpy(reply, header, prefix_len);
  memcpy(reply + prefix_len, text + start, text_len);
  memcpy(reply + prefix_len + text_len, next_command, suffix_len + 1);
}

// Only a recognized Reader request enters this 2 KiB decode frame. Normal
// framed commands must not reserve it, including with link-time optimization.
__attribute__((noinline)) void replyVerse(bible::Reference ref, uint8_t page,
                                        char* reply, size_t capacity) {
  char scratch[bible::kBlockSize];
  const char* text = nullptr;
  const bible::LookupResult result = readReaderVerse(ref, scratch, sizeof(scratch), text);
  if (result == bible::LookupResult::Found) {
    formatVerseReply(ref, page, text, reply, capacity);
  } else if (result == bible::LookupResult::Missing) {
    snprintf(reply, capacity, "This verse is not present in the supplied translation.");
  } else {
    snprintf(reply, capacity, "ERROR: invalid compressed Reader data");
  }
}

__attribute__((noinline)) void printReplyPage(bible::Reference ref, uint8_t page,
                                            Stream& output) {
  char reply[160];
  replyVerse(ref, page, reply, sizeof(reply));
  output.print("  ");
  output.print(reply);
  output.print("\r\n");
}

// Keep the decode buffer out of the parser's frame, including under LTO:
// unrelated terminal commands must not reserve another 2 KiB of stack.
__attribute__((noinline)) void printVerse(bible::Reference ref, Stream& output) {
  char scratch[bible::kBlockSize];
  const char* text = nullptr;
  const bible::LookupResult result = readReaderVerse(ref, scratch, sizeof(scratch), text);
  if (result == bible::LookupResult::Found) {
    output.printf("  Reader %u:%u (%s)\r\n", static_cast<unsigned>(ref.chapter),
                  static_cast<unsigned>(ref.verse), bible::generated::readerCorpus.translation);
    // Do not feed long text through Adafruit Print::printf's 256-byte scratch.
    output.print(text);
    output.print("\r\n");
    output.print(bible::generated::readerCorpus.attribution);
    output.print("\r\n");
  } else if (result == bible::LookupResult::Missing) {
    output.print("  This verse is not present in the supplied translation.\r\n");
  } else {
    output.print("  ERROR: invalid compressed Reader data\r\n");
  }
}

} // namespace

bool handleReaderCommand(const char* command, Stream& output) {
  bible::Reference ref = {};
  uint8_t page;
  const bible::ParseResult parsed = parseReaderRequest(command, ref, page);
  if (parsed == bible::ParseResult::NoMatch) return false;
  if (parsed == bible::ParseResult::Invalid) {
    output.print("  ERROR: use get reader <chapter>:<verse> [page] (example: get reader 3:16)\r\n");
  } else if (page != 0) {
    printReplyPage(ref, page, output);
  } else {
    printVerse(ref, output);
  }
  return true;
}

bool handleReaderReply(const char* command, char* reply, size_t capacity) {
  if (reply == nullptr || capacity == 0) return false;
  bible::Reference ref = {};
  uint8_t page;
  const bible::ParseResult parsed = parseReaderRequest(command, ref, page);
  if (parsed == bible::ParseResult::NoMatch) return false;
  if (parsed == bible::ParseResult::Invalid) {
    snprintf(reply, capacity, "ERROR: use get reader <chapter>:<verse> [page] (example: get reader 3:16)");
  } else {
    replyVerse(ref, page == 0 ? 1 : page, reply, capacity);
  }
  return true;
}

} // namespace mesh
#endif
