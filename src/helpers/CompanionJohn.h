#pragma once
#include "CompanionJohnConfig.h"

#if COMPANION_FEATURE_JOHN
#include "bible/JohnLookup.h"
class Stream;
namespace mesh {
// Caller-owned scratch lets the terminal and screen share one flash corpus.
bible::LookupResult readJohnVerse(bible::Reference ref, char* scratch,
                                 size_t capacity, const char*& text);
// Terminal-only: verses can exceed the framed/remote CLI's 160-byte reply.
bool handleJohnCommand(const char* command, Stream& output);
}
#endif
