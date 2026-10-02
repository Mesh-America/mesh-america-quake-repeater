#include "helpers/ui/CompactNotoFonts.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

using namespace mesh::ui::noto;
extern "C" const uint8_t* fontFromOtherTranslationUnit(unsigned id);
extern "C" int identifyInOtherTranslationUnit(const uint8_t* descriptor);

int main(int argc, char**) {
  uint8_t scratch[kScratchSize + 2];
  if (argc > 1) {
    const Glyph decoded = glyph(font(1), 33, scratch + 1, kScratchSize);
    assert(!decoded.valid);
    return 0;
  }
  assert(kScratchSize == 512);
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
        assert(!glyph(descriptor, uint8_t(code), nullptr, kScratchSize).valid);
        assert(!glyph(descriptor, uint8_t(code), scratch + 1, 0).valid);
      } else {
        assert(decoded.data == nullptr);
        assert(glyph(descriptor, uint8_t(code), nullptr, 0).valid);
      }
      printf("G %u %u %u %u ", id, code, decoded.width, decoded.length);
      for (unsigned index = 0; index < decoded.length; ++index) printf("%02x", decoded.data[index]);
      puts("");
    }
  }
  uint8_t first[kScratchSize], second[kScratchSize];
  const Glyph a = glyph(font(1), 'A', first, sizeof(first));
  uint8_t snapshot[kScratchSize];
  memcpy(snapshot, first, sizeof(first));
  const Glyph b = glyph(font(2), 'W', second, sizeof(second));
  assert(a.valid && b.valid);
  assert(memcmp(snapshot, first, sizeof(first)) == 0);
}
