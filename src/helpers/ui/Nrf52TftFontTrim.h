#pragma once

// Only the non-Companion nRF52 ST7735 renderer includes this configuration.
// Load the selected library setup first so its driver, bus and pin settings
// remain unchanged, then prevent TFT_eSPI from loading those settings again.
#if defined(NRF52_PLATFORM) && defined(MESH_NRF52_FLASH_TRIM) && MESH_NRF52_FLASH_TRIM
#include <User_Setup_Select.h>
#ifndef USER_SETUP_LOADED
#define USER_SETUP_LOADED
#endif

// ST7735Display uses the normal GLCD font and integer scaling. Keep GFXFF's
// no-argument setFreeFont() API; the numbered and smooth fonts are never used.
#undef LOAD_FONT2
#undef LOAD_FONT4
#undef LOAD_FONT6
#undef LOAD_FONT7
#undef LOAD_FONT8
#undef LOAD_FONT8N
#undef SMOOTH_FONT
#endif
