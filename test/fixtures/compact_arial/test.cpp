#include "helpers/ui/CompactArialFonts.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

using namespace mesh::ui::arial;
extern "C" const uint8_t* fontFromOtherTranslationUnit(unsigned id);
extern "C" int identifyInOtherTranslationUnit(const uint8_t* descriptor);

static void rleFailures() {
  uint8_t guarded[5] = { 0x5a, 0, 0, 0, 0xa5 };
  const uint8_t literal[] = { 2, 1, 2, 3 };
  assert(decodeRle(literal, sizeof(literal), guarded + 1, 3));
  assert(guarded[1] == 1 && guarded[2] == 2 && guarded[3] == 3);
  assert(!decodeRle(literal, sizeof(literal), guarded + 1, 2));
  assert(!decodeRle(literal, sizeof(literal) - 1, guarded + 1, 3));
  const uint8_t repeat[] = { 0x80, 7 };
  assert(decodeRle(repeat, sizeof(repeat), guarded + 1, 3));
  assert(guarded[1] == 7 && guarded[2] == 7 && guarded[3] == 7);
  assert(!decodeRle(repeat, 1, guarded + 1, 3));
  assert(!decodeRle(repeat, sizeof(repeat), guarded + 1, 2));
  assert(!decodeRle(repeat, sizeof(repeat), guarded + 1, 4));
  assert(!decodeRle(nullptr, 1, guarded + 1, 3));
  assert(!decodeRle(repeat, sizeof(repeat), nullptr, 3));
  assert(decodeRle(nullptr, 0, nullptr, 0));
  assert(guarded[0] == 0x5a && guarded[4] == 0xa5);
}

int main(int argc, char**) {
  uint8_t scratch[kScratchSize + 2];
  if (argc > 1) {
    // Python alters the descriptor or first stream in a private header copy.
    const Glyph decoded = glyph(font(1), 33, scratch + 1, kScratchSize);
    assert(!decoded.valid);
    return 0;
  }
  rleFailures();
  assert(font(0) == nullptr && font(3) == nullptr && font(100) == nullptr);
  assert(identify(nullptr) == -1);
  assert(!glyph(nullptr, 65, scratch + 1, kScratchSize).valid);
  for (unsigned id = 1; id <= 2; ++id) {
    const uint8_t* descriptor = font(id);
    assert(identify(descriptor) == int(id));
    assert(fontFromOtherTranslationUnit(id) == descriptor);
    assert(identifyInOtherTranslationUnit(descriptor) == int(id));
    uint8_t copy[900];
    memcpy(copy, descriptor, sizeof(copy));
    assert(identify(copy) == -1);
    assert(!glyph(copy, 65, scratch + 1, kScratchSize).valid);
    assert(!glyph(descriptor, 31, scratch + 1, kScratchSize).valid);
    printf("F %u %u %u %u %u\n", id, descriptor[0], descriptor[1], descriptor[2], descriptor[3]);
    for (unsigned code = descriptor[2]; code < unsigned(descriptor[2]) + descriptor[3]; ++code) {
      memset(scratch, 0xcc, sizeof(scratch));
      scratch[0] = 0x5a;
      scratch[sizeof(scratch) - 1] = 0xa5;
      const Glyph decoded = glyph(descriptor, uint8_t(code), scratch + 1, kScratchSize);
      assert(decoded.valid);
      assert(decoded.drawable == (decoded.length > 0));
      assert(scratch[0] == 0x5a && scratch[sizeof(scratch) - 1] == 0xa5);
      const uint8_t* record = descriptor + 4 + 4 * (code - descriptor[2]);
      assert(record[2] == decoded.length && record[3] == decoded.width);
      if (decoded.drawable) {
#if MESH_ARIAL_EXPERIMENT == 2
        if (!(record[0] & 0x80)) {
          assert(!glyph(descriptor, uint8_t(code), nullptr, kScratchSize).valid);
          assert(!glyph(descriptor, uint8_t(code), scratch + 1, decoded.length - 1).valid);
        }
#else
        assert(!glyph(descriptor, uint8_t(code), nullptr, kScratchSize).valid);
        assert(!glyph(descriptor, uint8_t(code), scratch + 1, 0).valid);
#endif
      } else {
        assert(decoded.data == nullptr);
        assert(glyph(descriptor, uint8_t(code), nullptr, 0).valid);
      }
      printf("G %u %u %u %u ", id, code, decoded.width, decoded.length);
      for (unsigned index = 0; index < decoded.length; ++index) printf("%02x", decoded.data[index]);
      puts("");
    }
  }
}
