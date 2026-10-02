#include "helpers/ui/CompactNotoFonts.h"

extern "C" const uint8_t* fontFromOtherTranslationUnit(unsigned id) {
  return mesh::ui::noto::font(id);
}

extern "C" int identifyInOtherTranslationUnit(const uint8_t* descriptor) {
  return mesh::ui::noto::identify(descriptor);
}
