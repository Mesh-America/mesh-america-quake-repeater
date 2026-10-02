#include "helpers/ui/CompactArialFonts.h"

extern "C" const uint8_t* fontFromOtherTranslationUnit(unsigned id) {
  return mesh::ui::arial::font(id);
}

extern "C" int identifyInOtherTranslationUnit(const uint8_t* descriptor) {
  return mesh::ui::arial::identify(descriptor);
}
