#pragma once
#include "CompanionReaderConfig.h"
#include <stddef.h>
#include <stdint.h>

class Stream;
namespace mesh {
using ReaderTryWrite = size_t (*)(Stream&, const uint8_t*, size_t);
}
#if COMPANION_FEATURE_READER
#include "bible/ReaderLookup.h"
namespace mesh {
// Caller-owned scratch lets the terminal and screen share one flash corpus.
bible::LookupResult readReaderVerse(bible::Reference ref, char* scratch,
                                 size_t capacity, const char*& text);
// Text terminals stream complete chapters/verse ranges cooperatively. Each
// service call writes at most 96 bytes, retaining progress after short writes.
// The owner must cancel before ending a session or destroying its Stream.
// try_write lets a transport bypass its ordinary blocking Stream::write.
bool handleReaderCommand(const char* command, Stream& output, bool prompt = false,
                         ReaderTryWrite try_write = nullptr);
void serviceReaderCommand();
void cancelReaderCommand(const Stream* output = nullptr);
bool readerCommandActive(const Stream* output = nullptr);
// Existing USB/BLE CLI frames contain one bounded reply. Short verses are
// complete; longer verses/ranges include the command for their next page.
bool handleReaderReply(const char* command, char* reply, size_t capacity);
}
#endif
