#include <helpers/NoiseFloorHistory.h>

#include <assert.h>
#include <limits>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>

using mesh::NoiseFloorHistory;
static constexpr uint32_t BASE = 1700000100UL;
static const uint8_t SOURCE[8] = {1, 2, 3, 4, 5, 6, 7, 8};

static uint32_t little32(const uint8_t* bytes) {
  return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8)
      | ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static std::vector<uint8_t> decode(const char* reply) {
  assert(strncmp(reply, "> ", 2) == 0);
  const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::vector<uint8_t> bytes;
  const std::string text = reply + 2;
  assert(text.size() % 4 == 0);
  uint32_t accumulator = 0;
  unsigned bits = 0;
  bool padding = false;
  for (char ch : text) {
    if (ch == '=') { padding = true; continue; }
    assert(!padding);
    const char* found = strchr(alphabet, ch);
    assert(found != nullptr);
    accumulator = (accumulator << 6) | (uint32_t)(found - alphabet);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push_back((uint8_t)(accumulator >> bits));
    }
  }
  assert(bits == 0 || (accumulator & ((1U << bits) - 1U)) == 0);
  return bytes;
}

static uint8_t code(const uint8_t* packed, size_t index) {
  const size_t byte = index * 5U / 8U;
  const unsigned shift = (unsigned)(index * 5U % 8U);
  const uint16_t word = (uint16_t)((uint16_t)packed[byte] << 8)
      | (shift > 3 ? packed[byte + 1] : 0);
  return (uint8_t)((word >> (11U - shift)) & 31U);
}

static void collect(NoiseFloorHistory& history, uint32_t start,
                    float a, float b, float c, uint8_t profile = 0) {
  history.advance(start);
  assert(history.observe(profile, start + 1, a, (start + 1) * 1000U));
  assert(history.observe(profile, start + 301, b, (start + 301) * 1000U));
  assert(history.observe(profile, start + 601, c, (start + 601) * 1000U));
}

static uint8_t single(float a, float b, float c) {
  NoiseFloorHistory history;
  collect(history, BASE, a, b, c);
  assert(history.sampleCount(0) == 0);
  history.advance(BASE + 900);
  assert(history.sampleCount(0) == 1);
  return history.sampleCodeAtOffset(0, 0);
}

static void selection() {
  assert(single(-120, -90, -60) == 0); // Low wins across the entire range.
  assert(single(-119, -80, -90) == 1);
  assert(single(-118, -117, -116) == 2);
  assert(single(-119.1f, -110, -100) == 0);
  assert(single(-118.1f, -110, -100) == 1);
  assert(single(-117, -110, -100) == 2);
  assert(single(-101, -90, -80) == 10); // Minimum rounds down to -102.
  assert(single(-100, -90, -70) == 11); // Threshold is inclusive.
  assert(single(-91, -90, -89) == 16);  // Middle averages to -90.
  assert(single(-91, -90, -90) == 16); // Average rounds nearest, not down.
  assert(single(-99, -90, -80) == 21); // Maximum threshold is inclusive.
  assert(single(-90, -79, -85) == 22); // Maximum rounds up to -78.
  assert(single(-100.01f, -60, -60) == 10);
  assert(single(-130, -150, -121) == 0);
  assert(single(-70, -65, -90) == 29); // -65 rounds up to -64.
  assert(single(-70, -64, -90) == 29);
  assert(single(-70, -63.99f, -90) == NoiseFloorHistory::MAX);
  assert(single(-20, -70, -80) == NoiseFloorHistory::MAX);
}

static void freshness() {
  NoiseFloorHistory history;
  assert(!history.observe(0, BASE, -110, 1)); // advance establishes RTC.
  history.advance(BASE);
  assert(history.observe(0, BASE + 1, -120, 1));
  assert(!history.observe(0, BASE + 301, -90, 1)); // Same calibration is stale.
  assert(!history.observe(0, BASE + 2, std::numeric_limits<float>::quiet_NaN(), 2));
  assert(!history.observe(0, BASE + 2, std::numeric_limits<float>::infinity(), 2));
  assert(!history.observe(0, BASE + 2, -201, 2));
  assert(!history.observe(0, BASE + 2, 1, 2));
  assert(!history.observe(2, BASE + 2, -90, 2));
  assert(!history.observe(0, BASE - 1, -90, 2));
  assert(!history.observe(0, BASE + 900, -90, 2));
  assert(history.observe(0, BASE + 2, -110, 2)); // Latest in one slot replaces.
  assert(!history.observe(0, BASE + 1, -120, 3)); // Older publication ignored.
  assert(history.observe(0, BASE + 301, -90, 3));
  assert(history.observe(0, BASE + 601, -80, 4));
  history.advance(BASE + 900);
  assert(history.sampleCodeAtOffset(0, 0) == 6); // -110, not superseded -120.
  assert(history.sampleCodeAtOffset(1, 0) == NoiseFloorHistory::MISSING);
  assert(history.hasValidSamples(0));
  assert(!history.hasValidSamples(1));
  assert(!history.observe(0, BASE + 601, -80, 4));
  assert(!history.observe(0, BASE + 901, -80, 4)); // Watermark crosses bucket.
  assert(history.observe(0, BASE + 901, -80, 5));
  assert(history.observe(0, BASE + 1501, -80, 6));
  history.advance(BASE + 1800); // Two subslots cannot masquerade as three.
  assert(history.sampleCodeAtOffset(0, 0) == NoiseFloorHistory::MISSING);
  assert(history.sampleCodeAtOffset(0, 1) == 6);

  NoiseFloorHistory wrapped;
  wrapped.advance(BASE);
  assert(wrapped.observe(0, BASE + 1, -110, 0xFFFFFFFEUL));
  assert(wrapped.observe(0, BASE + 1, -110, 1));
  assert(!wrapped.observe(0, BASE + 1, -120, 0xFFFFFFFDUL));
  assert(wrapped.observe(0, BASE + 301, -110, 300001));
  assert(wrapped.observe(0, BASE + 601, -110, 600001));
  wrapped.advance(BASE + 900);
  assert(wrapped.sampleCodeAtOffset(0, 0) == 6);
}

static void invalidation() {
  NoiseFloorHistory history;
  collect(history, BASE, -120, -119, -118);
  collect(history, BASE, -70, -71, -72, 1);
  history.invalidateProfile(0);
  assert(!history.observe(0, BASE + 601, -118, (BASE + 601) * 1000U));
  history.advance(BASE + 900);
  assert(history.sampleCodeAtOffset(0, 0) == NoiseFloorHistory::MISSING);
  assert(history.sampleCodeAtOffset(1, 0) == 26);
  collect(history, BASE + 900, -119, -118, -117);
  history.advance(BASE + 1800);
  history.invalidateProfile(0);
  history.invalidateProfile(255);
  assert(history.sampleCodeAtOffset(0, 0) == 1); // Completed data retained.
  assert(history.sampleCount(255) == 0);
  assert(!history.hasValidSamples(255));
}

static void rollover() {
  NoiseFloorHistory history;
  assert(history.storageBytes() == 960);
  for (unsigned i = 0; i < 800; ++i) {
    collect(history, BASE + i * 900U, -120.0f + (float)(i % 3), -90, -85);
    history.advance(BASE + (i + 1U) * 900U);
  }
  assert(history.sampleCount(0) == 768);
  assert(history.sampleCount(1) == 768);
  for (unsigned offset = 0; offset < 768; ++offset) {
    assert(history.sampleCodeAtOffset(0, (uint16_t)offset) == (799 - offset) % 3);
    assert(history.sampleCodeAtOffset(1, (uint16_t)offset) == NoiseFloorHistory::MISSING);
  }
  assert(history.sampleCodeAtOffset(0, 768) == NoiseFloorHistory::MISSING);
  char reply[160];
  assert(history.formatPageReply(0, "5", reply));
  const auto bytes = decode(reply);
  assert(bytes[6] == 64);
  assert(little32(bytes.data() + 1) == BASE + 32U * 900U);
  for (unsigned i = 0; i < 64; ++i) assert(code(bytes.data() + 7, i) == (32 + i) % 3);
}

static void clockChanges() {
  NoiseFloorHistory history;
  collect(history, BASE, -119, -90, -90);
  history.advance(BASE + 3600);
  assert(history.sampleCount(0) == 4);
  assert(history.sampleCodeAtOffset(0, 3) == 1);
  for (unsigned i = 0; i < 3; ++i) assert(history.sampleCodeAtOffset(0, i) == 31);
  history.advance(BASE + 3599); // Current bucket moves backwards.
  assert(history.sampleCount(0) == 0);
  assert(!history.hasValidSamples(0));
  collect(history, BASE + 2700, -118, -90, -90);
  history.advance(BASE + 3600);
  assert(history.sampleCodeAtOffset(0, 0) == 2);
  history.advance(BASE + 3600 + (768U + 1U) * 900U);
  assert(history.sampleCount(0) == 0); // Huge jump is bounded and starts fresh.
  const uint32_t high = 0xFFFFFFFFUL / 900U * 900U;
  history.advance(high);
  assert(history.sampleCount(0) == 0);
  history.advance(0);
  assert(history.sampleCount(0) == 0);
  assert(history.observe(0, 1, -120, 1));
  assert(history.observe(0, 301, -120, 2));
  assert(history.observe(0, 601, -120, 3));
  history.advance(900);
  char reply[160];
  assert(history.formatPageReply(0, "", reply));
  assert(little32(decode(reply).data() + 1) == 0);
}

static void wire() {
  NoiseFloorHistory history;
  struct Guarded { char before; char reply[160]; char after; } guard;
  memset(&guard, 0x5A, sizeof(guard));
  assert(!history.formatPageReply(0, "", guard.reply));
  assert(strstr(guard.reply, "empty") != nullptr);
  assert(!history.formatPageReply(0, "1", nullptr));
  assert(!history.formatPageReply(0, "1", guard.reply, 0));
  for (unsigned i = 0; i < 300; ++i) {
    collect(history, BASE + i * 900U, -120.0f + (float)(i % 3), -90, -90);
    collect(history, BASE + i * 900U, -65, -70, -90, 1);
    history.advance(BASE + (i + 1U) * 900U);
  }
  assert(history.formatPageReply(0, " 1 ", guard.reply));
  assert(strlen(guard.reply) == 158);
  assert(guard.before == 0x5A && guard.after == 0x5A);
  auto bytes = decode(guard.reply);
  assert(bytes.size() == 117 && bytes[0] == 0x15);
  assert(little32(bytes.data() + 1) == BASE + 124U * 900U);
  assert(bytes[5] == 15 && bytes[6] == 176);
  for (unsigned i = 0; i < 176; ++i) assert(code(bytes.data() + 7, i) == (124 + i) % 3);
  assert(history.formatPageReply(1, "2", guard.reply));
  bytes = decode(guard.reply);
  assert(bytes[0] == 0x16 && bytes[6] == 124);
  assert(little32(bytes.data() + 1) == BASE);
  for (unsigned i = 0; i < 124; ++i) assert(code(bytes.data() + 7, i) == 29);
  assert((bytes.back() & 0x0FU) == 0); // Four final packing bits are padding.
  assert(!history.formatPageReply(0, "3", guard.reply));
  for (const char* arg : {"0", "6", "-1", "1x", "1 2", "9999999999999999999999"}) {
    assert(!history.formatPageReply(0, arg, guard.reply));
  }
  assert(!history.formatPageReply(2, "", guard.reply));
  assert(!history.formatPageReply(0, "1", guard.reply, 158));
  assert(history.formatPageReply(0, "1", guard.reply, 159));
  assert(guard.before == 0x5A && guard.after == 0x5A);
  struct Correlated { char before; char reply[160]; char after; } correlated;
  memset(&correlated, 0x5A, sizeof(correlated));
  memcpy(correlated.reply, "ab|", 3);
  assert(history.formatPageReply(0, "1", correlated.reply + 3, 157, false));
  assert(strlen(correlated.reply) == 159);
  assert(memcmp(correlated.reply, "ab|", 3) == 0);
  assert(strcmp(correlated.reply + 3, guard.reply + 2) == 0);
  assert(decode((std::string("> ") + (correlated.reply + 3)).c_str()) == decode(guard.reply));
  assert(correlated.before == 0x5A && correlated.after == 0x5A);
  struct Bare { char before; char reply[157]; char after; } bare;
  memset(&bare, 0x5A, sizeof(bare));
  assert(history.formatPageReply(0, "1", bare.reply, sizeof(bare.reply), false));
  assert(strlen(bare.reply) == 156 && strcmp(bare.reply, guard.reply + 2) == 0);
  assert(!history.formatPageReply(0, "1", bare.reply, 156, false));
  assert(strncmp(bare.reply, "Err", 3) == 0);
  assert(bare.before == 0x5A && bare.after == 0x5A);

  uint8_t raw[186];
  memset(raw, 0xA5, sizeof(raw));
  assert(history.formatBinarySnapshot(0, SOURCE, raw + 1, 184) == 179);
  assert(memcmp(raw + 1, "N1B1", 4) == 0 && memcmp(raw + 5, SOURCE, 8) == 0);
  assert(little32(raw + 13) == BASE + 45U * 900U);
  assert(raw[17] == 15 && raw[18] == 0 && raw[19] == 255);
  for (unsigned i = 0; i < 255; ++i) assert(code(raw + 20, i) == (45 + i) % 3);
  assert((raw[179] & 0x1FU) == 0); // 255*5 leaves five padding bits.
  assert(raw[0] == 0xA5 && raw[180] == 0xA5 && raw[185] == 0xA5);
  assert(history.formatBinarySnapshot(1, SOURCE, raw + 1, 20) == 20);
  assert(memcmp(raw + 1, "N2B1", 4) == 0 && raw[19] == 1);
  assert(code(raw + 20, 0) == 29);
  assert(little32(raw + 13) == BASE + 299U * 900U);
  assert(history.formatBinarySnapshot(0, SOURCE, raw, 19) == 0);
  assert(history.formatBinarySnapshot(2, SOURCE, raw, sizeof(raw)) == 0);
  assert(history.formatBinarySnapshot(0, nullptr, raw, sizeof(raw)) == 0);
  assert(history.formatBinarySnapshot(0, SOURCE, nullptr, sizeof(raw)) == 0);
  // Missing is an explicit usable code, including disabled-profile history.
  NoiseFloorHistory missing;
  missing.advance(BASE);
  missing.advance(BASE + 900);
  assert(missing.formatBinarySnapshot(1, SOURCE, raw, sizeof(raw)) == 20);
  assert(raw[18] == 1 && code(raw + 19, 0) == 31);
  assert(missing.formatPageReply(1, "", guard.reply));
  bytes = decode(guard.reply);
  assert(bytes.size() == 8 && code(bytes.data() + 7, 0) == 31);
  assert(strchr(guard.reply, '=') != nullptr); // Standard padded Base64.

  // Independent MSB-first wire vector: eight five-bit codes 0..7.
  NoiseFloorHistory golden;
  const float levels[] = {-120, -119, -118, -116, -114, -112, -110, -108};
  for (unsigned i = 0; i < 8; ++i) {
    collect(golden, BASE + i * 900U, levels[i], levels[i], levels[i]);
    golden.advance(BASE + (i + 1U) * 900U);
  }
  assert(golden.formatBinarySnapshot(0, SOURCE, raw, sizeof(raw)) == 24);
  const uint8_t expected[] = {0x00, 0x44, 0x32, 0x14, 0xC7};
  assert(memcmp(raw + 19, expected, sizeof(expected)) == 0);
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario(argv[1]);
  if (scenario == "selection") selection();
  else if (scenario == "freshness") freshness();
  else if (scenario == "invalidation") invalidation();
  else if (scenario == "rollover") rollover();
  else if (scenario == "clock") clockChanges();
  else if (scenario == "wire") wire();
  else return 2;
  puts("noise floor history: ok");
}
