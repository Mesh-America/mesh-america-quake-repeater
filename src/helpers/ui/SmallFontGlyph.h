#pragma once

#include <stdint.h>

namespace mesh {
namespace ui {

// Packed monochrome bitmap metrics, with GFX-style baseline offsets.
struct SmallFontGlyph {
  uint16_t bitmap_offset;
  uint8_t width, height, advance;
  int8_t x_offset, y_offset;
};

}  // namespace ui
}  // namespace mesh
