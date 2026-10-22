#include <helpers/ui/PocketGuiSettings.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <limits>

using namespace mesh::ui::pocket;

static bool equal(const Settings& left, const Settings& right) {
  return left.channel == right.channel && left.text_large == right.text_large
      && left.name_len == right.name_len && left.flip == right.flip
      && left.dark == right.dark && left.idle == right.idle
      && left.refresh == right.refresh && left.map_zoom == right.map_zoom;
}

static void repairChecksum(uint8_t* bytes) {
  const uint16_t crc = settingsChecksum(bytes, 11);
  bytes[11] = static_cast<uint8_t>(crc);
  bytes[12] = static_cast<uint8_t>(crc >> 8);
}

static void settingsRoundTrip() {
  Settings value;
  assert(settingsValid(value));
  assert(idleMillis(value) == 60000 && refreshCount(value) == 10);
  assert(nameCharacters(value) == 5 && mapHeightKm(value) == 200);

  uint8_t bytes[SETTINGS_RECORD_SIZE];
  for (unsigned channels : {1U, 40U, 256U}) {
    for (unsigned choices = 0; choices < 8; ++choices)
      for (unsigned name = 0; name < 4; ++name)
        for (unsigned idle = 0; idle < 4; ++idle)
          for (unsigned refresh = 0; refresh < 4; ++refresh)
            for (unsigned zoom = 0; zoom < 9; ++zoom) {
              value.channel = static_cast<uint8_t>(channels - 1);
              value.text_large = choices & 1;
              value.flip = (choices >> 1) & 1;
              value.dark = (choices >> 2) & 1;
              value.name_len = name;
              value.idle = idle;
              value.refresh = refresh;
              value.map_zoom = zoom;
              assert(encodeSettings(value, bytes, sizeof(bytes), channels));
              Settings recovered;
              assert(decodeSettings(recovered, bytes, sizeof(bytes), channels));
              assert(equal(value, recovered));
            }
  }

  value = Settings{};
  assert(encodeSettings(value, bytes, sizeof(bytes)));
  const Settings sentinel{39, 1, 3, 1, 1, 3, 3, 8};
  auto rejects = [&](const uint8_t* input, size_t size, unsigned channels = 40) {
    Settings destination = sentinel;
    assert(!decodeSettings(destination, input, size, channels));
    assert(equal(destination, sentinel));
  };
  rejects(nullptr, sizeof(bytes));
  for (size_t size = 0; size < sizeof(bytes); ++size) rejects(bytes, size);
  rejects(bytes, sizeof(bytes) + 1);
  rejects(bytes, sizeof(bytes), 0);
  rejects(bytes, sizeof(bytes), 257);

  // Detect corruption at every bit, including the stored checksum itself.
  for (size_t byte = 0; byte < sizeof(bytes); ++byte)
    for (unsigned bit = 0; bit < 8; ++bit) {
      uint8_t changed[sizeof(bytes)];
      std::memcpy(changed, bytes, sizeof(bytes));
      changed[byte] ^= 1U << bit;
      rejects(changed, sizeof(changed));
    }

  // A record with a valid CRC still cannot select invalid enum values, a
  // missing channel, an unknown format or reserved bits.
  const unsigned bad_offsets[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
  const unsigned bad_values[] = {'X', 'X', 3, 40, 2, 4, 4, 4, 4, 9, 1};
  for (size_t test = 0; test < sizeof(bad_offsets) / sizeof(*bad_offsets); ++test) {
    uint8_t changed[sizeof(bytes)];
    std::memcpy(changed, bytes, sizeof(bytes));
    changed[bad_offsets[test]] = bad_values[test];
    repairChecksum(changed);
    rejects(changed, sizeof(changed));
  }

  // Migrate each old cleanup choice without resetting any other settings.
  for (unsigned old_refresh = 0; old_refresh < 4; ++old_refresh) {
    Settings old{39, 1, 3, 1, 1, 2, static_cast<uint8_t>(old_refresh), 8};
    assert(encodeSettings(old, bytes, sizeof(bytes)));
    bytes[2] = 1;
    repairChecksum(bytes);
    Settings migrated;
    assert(decodeSettings(migrated, bytes, sizeof(bytes)));
    old.refresh = 3;
    assert(equal(migrated, old) && refreshCount(migrated) == 10);
  }
  const int cleanup_counts[] = {1, 3, 5, 10};
  for (unsigned choice = 0; choice < 4; ++choice) {
    value.refresh = choice;
    assert(refreshCount(value) == cleanup_counts[choice]);
  }

  value.channel = 39;
  assert(encodeSettings(value, bytes, sizeof(bytes), 40));
  rejects(bytes, sizeof(bytes), 39);
  for (unsigned row = 0; row < SETTINGS_COUNT; ++row) {
    Settings changed;
    const Settings initial = changed;
    const unsigned periods[] = {40, 2, 4, 2, 2, 4, 4, 9};
    for (unsigned step = 0; step < periods[row]; ++step) {
      assert(cycleSetting(changed, row));
      assert(settingsValid(changed));
    }
    assert(equal(changed, initial));
  }
  const Settings initial;
  value = initial;
  assert(!cycleSetting(value, SETTINGS_COUNT) && equal(value, initial));
  assert(!cycleSetting(value, 0, 0) && equal(value, initial));
  assert(!cycleSetting(value, 0, 257) && equal(value, initial));
  value.channel = 255;
  assert(cycleSetting(value, 0, 256) && value.channel == 0);

  for (unsigned bad = 4; bad <= 255; ++bad) {
    value.idle = value.refresh = value.name_len = static_cast<uint8_t>(bad);
    assert(idleMillis(value) == 60000 && refreshCount(value) == 10);
    assert(nameCharacters(value) == 5);
  }
  for (unsigned bad = 9; bad <= 255; ++bad) {
    value.map_zoom = static_cast<uint8_t>(bad);
    assert(mapHeightKm(value) == 200);
  }
}

static void scrollHistory() {
  assert(messageAgeSeconds(1000, UINT32_MAX - 999U) == 2);
  assert(messageAgeSeconds(180000, 60000) == 120);
  for (unsigned count = 0; count <= 32; ++count) {
    BoardState state;
    assert(!state.scrollNewer());
    for (unsigned next = 1; next < count; ++next) {
      assert(state.scrollOlder(count));
      assert(state.scroll == next);
    }
    assert(!state.scrollOlder(count));
    assert(state.scroll == (count == 0 ? 0 : count - 1));
    const unsigned previous = state.scroll;
    state.messageAdded();
    // At the live end keep following new messages. While reading old messages
    // retain the same entry until it falls out of the 32-message ring.
    assert(state.scroll == (previous == 0 ? 0 : previous < 31 ? previous + 1 : 31));
    state.clamp(0);
    assert(state.scroll == 0);
  }
  BoardState state;
  state.scroll = std::numeric_limits<unsigned>::max();
  state.clamp(1);
  assert(state.scroll == 0 && !state.scrollOlder(1));
  state.scroll = 99;
  state.clamp(32);
  assert(state.scroll == 31 && !state.scrollOlder(32));
  for (unsigned left = 31; left > 0; --left) {
    assert(state.scrollNewer());
    assert(state.scroll == left - 1);
  }
  assert(!state.scrollNewer());
}

static void messageNamesAndText() {
  BoardMessageView result;
  parseBoardMessage("Ch 0 Public [1h]:", "Alice: hello: there", false, result);
  assert(result.sender_length == 5 && std::strncmp(result.sender, "Alice", 5) == 0);
  assert(std::strcmp(result.text, "hello: there") == 0);
  parseBoardMessage("My name", "Alice: literal outgoing body", true, result);
  assert(result.sender_length == 7 && std::strcmp(result.sender, "My name") == 0);
  assert(std::strcmp(result.text, "Alice: literal outgoing body") == 0);
  parseBoardMessage("Alice [direct]:", "no sender prefix", false, result);
  assert(result.sender_length == 5 && std::strcmp(result.text, "no sender prefix") == 0);
  parseBoardMessage(nullptr, nullptr, false, result);
  assert(result.sender_length == 0 && *result.text == 0);
  parseBoardMessage("fallback [direct]:", ": invalid empty sender", false, result);
  assert(result.sender_length == 8);
  char long_message[90];
  std::memset(long_message, 'a', 70);
  std::strcpy(long_message + 70, ": message");
  parseBoardMessage("fallback", long_message, false, result);
  assert(result.sender_length == 8 && result.text == long_message);

  char text[64];
  sanitizeText(text, sizeof(text), "caf\xc3\xa9\t\xf0\x9f\x93\xbb\n!", 13);
  assert(std::strcmp(text, "caf\xc3\xa9 * !") == 0);
  sanitizeText(text, sizeof(text), nullptr, 100);
  assert(*text == 0);
  sanitizeText(text, 1, "abc", 3);
  assert(*text == 0);
  // Neither an exact-length nonterminated input nor a truncated multibyte
  // input can over-read, and a small output never ends with half of Latin-1.
  const char exact[] = {'a', 'b', 'c'};
  sanitizeText(text, sizeof(text), exact, sizeof(exact));
  assert(std::strcmp(text, "abc") == 0);
  const char truncated[] = {'a', '\xc3'};
  sanitizeText(text, sizeof(text), truncated, sizeof(truncated));
  assert(std::strcmp(text, "a*") == 0);
  sanitizeText(text, sizeof(text), "A\xc2\x85" "B", 4);
  assert(std::strcmp(text, "A B") == 0);
  sanitizeText(text, 3, "a\xc3\xa9", 3);
  assert(std::strcmp(text, "a") == 0);
  std::strcpy(text, "\xc3\x89lise");
  truncateCharacters(text, 3);
  assert(std::strcmp(text, "\xc3\x89li") == 0);
  truncateCharacters(text, 0);
  assert(std::strcmp(text, "\xc3\x89li") == 0);
  truncateCharacters(text, 1);
  assert(std::strcmp(text, "\xc3\x89") == 0);
}

int main() {
  settingsRoundTrip();
  scrollHistory();
  messageNamesAndText();
}
