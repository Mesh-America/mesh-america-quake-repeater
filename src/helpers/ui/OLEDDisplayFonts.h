#ifndef OLEDDISPLAYFONTS_h
#define OLEDDISPLAYFONTS_h

// Qualified nRF52 infrastructure defaults to mode 9; Companions remain mode 0.
// Optional comparisons: 0 = original, 1 = omit unused Arial10, 2 = per-glyph RLE,
// 3 = Zopfli-1000 chunks, 4 = Liberation Sans, 5 = Noto Sans,
// 6 = DejaVu Sans, 7 = Noto Sans Condensed, 8 = DejaVu Sans Condensed.
// Family trials preserve the visible 12/17px cap heights.
#include "Nrf52FontConfig.h"

#ifdef ARDUINO
#include <Arduino.h>
#elif __MBED__
#define PROGMEM
#endif

extern const uint8_t ArialMT_Plain_10[] PROGMEM;
#if MESHCORE_ARIAL_FONT_MODE == 9
#include "CompactNotoFonts.h"
namespace mesh { namespace ui { namespace active_compact_font = noto; } }
// Keep the display driver's existing font-selection API, with Noto glyphs.
#define ArialMT_Plain_16 (::mesh::ui::noto::font(1))
#define ArialMT_Plain_24 (::mesh::ui::noto::font(2))
#elif MESHCORE_ARIAL_FONT_MODE == 2 || MESHCORE_ARIAL_FONT_MODE == 3
#include "CompactArialFonts.h"
namespace mesh { namespace ui { namespace active_compact_font = arial; } }
#define ArialMT_Plain_16 (::mesh::ui::arial::font(1))
#define ArialMT_Plain_24 (::mesh::ui::arial::font(2))
#elif MESHCORE_ARIAL_FONT_MODE >= 4
#include "FontFamilyTrials.h"
#define ArialMT_Plain_16 (::mesh::ui::font_trials::font(1))
#define ArialMT_Plain_24 (::mesh::ui::font_trials::font(2))
#else
extern const uint8_t ArialMT_Plain_16[] PROGMEM;
extern const uint8_t ArialMT_Plain_24[] PROGMEM;
#endif
#endif
