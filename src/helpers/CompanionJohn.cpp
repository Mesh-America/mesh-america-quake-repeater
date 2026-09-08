#include "CompanionJohn.h"

#if COMPANION_FEATURE_JOHN
#include <Arduino.h>
#include "bible/JohnLookup.h"

#include "bible/JohnData.generated.h"

namespace mesh {
bible::LookupResult readJohnVerse(bible::Reference ref, char* scratch,
                                 size_t capacity, const char*& text) {
  return bible::lookup(bible::generated::johnCorpus, ref, scratch, capacity, text);
}

namespace {

// Keep the decode buffer out of the parser's frame, including under LTO:
// unrelated terminal commands must not reserve another 2 KiB of stack.
__attribute__((noinline)) void printVerse(bible::Reference ref, Stream& output) {
  char scratch[bible::kBlockSize];
  const char* text = nullptr;
  const bible::LookupResult result = readJohnVerse(ref, scratch, sizeof(scratch), text);
  if (result == bible::LookupResult::Found) {
    output.printf("  John %u:%u (%s)\r\n", static_cast<unsigned>(ref.chapter),
                  static_cast<unsigned>(ref.verse), bible::generated::johnCorpus.translation);
    // Do not feed long text through Adafruit Print::printf's 256-byte scratch.
    output.print(text);
    output.print("\r\n");
    output.print(bible::generated::johnCorpus.attribution);
    output.print("\r\n");
  } else if (result == bible::LookupResult::Missing) {
    output.print("  This verse is not present in the supplied translation.\r\n");
  } else {
    output.print("  ERROR: invalid compressed John data\r\n");
  }
}

} // namespace

bool handleJohnCommand(const char* command, Stream& output) {
  bible::Reference ref = {};
  const bible::ParseResult parsed = bible::parse(command, ref);
  if (parsed == bible::ParseResult::NoMatch) return false;
  if (parsed == bible::ParseResult::Invalid) {
    output.print("  ERROR: use get John <chapter>:<verse> (example: get John 3:16)\r\n");
  } else {
    printVerse(ref, output);
  }
  return true;
}

} // namespace mesh
#endif
