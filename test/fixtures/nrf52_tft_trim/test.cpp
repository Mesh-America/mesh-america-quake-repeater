#include "helpers/ui/Nrf52TftFontTrim.h"
#include <User_Setup_Select.h>

#if !defined(ILI9341_DRIVER) || TFT_CS != 42 || SPI_FREQUENCY != 40000000
#error "The trim changed the selected hardware setup"
#endif
#if !defined(LOAD_GLCD) || !defined(LOAD_GFXFF)
#error "The current bitmap font or setFreeFont API was removed"
#endif

#if EXPECT_TRIM
#if defined(LOAD_FONT2) || defined(LOAD_FONT4) || defined(LOAD_FONT6) || \
    defined(LOAD_FONT7) || defined(LOAD_FONT8) || defined(LOAD_FONT8N) || \
    defined(SMOOTH_FONT)
#error "Unused fonts are still enabled"
#endif
#ifndef USER_SETUP_LOADED
#error "The selected setup could reload the unused fonts"
#endif
#else
#if !defined(LOAD_FONT2) || !defined(LOAD_FONT4) || !defined(LOAD_FONT6) || \
    !defined(LOAD_FONT7) || !defined(LOAD_FONT8) || !defined(LOAD_FONT8N) || \
    !defined(SMOOTH_FONT)
#error "An excluded build lost its original fonts"
#endif
#endif

int main() { return 0; }
