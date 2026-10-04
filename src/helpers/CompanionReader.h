#pragma once
#include "CompanionReaderConfig.h"

#if COMPANION_FEATURE_READER
#include "bible/ReaderLookup.h"
class Stream;
namespace mesh {
// Caller-owned scratch lets the terminal and screen share one flash corpus.
bible::LookupResult readReaderVerse(bible::Reference ref, char* scratch,
                                 size_t capacity, const char*& text);
// Text terminals stream complete verses; an explicit page matches CLI replies.
bool handleReaderCommand(const char* command, Stream& output);
// Existing USB/BLE CLI frames contain one bounded reply. Short verses are
// complete; longer verses include the command for their next page.
bool handleReaderReply(const char* command, char* reply, size_t capacity);
}
#endif
