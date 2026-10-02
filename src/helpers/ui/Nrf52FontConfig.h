#pragma once

// The infrastructure pre-script sets MESH_NRF52_FLASH_TRIM only for known
// non-Companion nRF52 roles. Other display drivers and platforms stay unchanged.
// This header is also read by the C tinf wrapper, so keep it preprocessor-only.
// 9 = Noto Sans Condensed 16/24, Zopfli 1000, no unused initial Arial10.
// MESH_NRF52_FONT_MODE=0 opts out of the font change without disabling other
// infrastructure trims. The old experiment switch remains for comparisons.
#if defined(NRF52_PLATFORM) && defined(MESH_NRF52_FLASH_TRIM) \
    && MESH_NRF52_FLASH_TRIM && defined(ST7789) \
    && !defined(COMPANION_RADIO_FULL)
#if defined(MESH_ARIAL_EXPERIMENT)
#define MESHCORE_ARIAL_FONT_MODE MESH_ARIAL_EXPERIMENT
#elif defined(MESH_NRF52_FONT_MODE)
#define MESHCORE_ARIAL_FONT_MODE MESH_NRF52_FONT_MODE
#else
#define MESHCORE_ARIAL_FONT_MODE 9
#endif
#else
#define MESHCORE_ARIAL_FONT_MODE 0
#endif

#if MESHCORE_ARIAL_FONT_MODE < 0 || MESHCORE_ARIAL_FONT_MODE > 9
#error "Unsupported nRF52 font mode (expected 0..9)"
#endif

#define MESHCORE_FONT_DEFLATE \
    (MESHCORE_ARIAL_FONT_MODE == 3 || MESHCORE_ARIAL_FONT_MODE == 9)
#define MESHCORE_FONT_COMPRESSED \
    (MESHCORE_ARIAL_FONT_MODE == 2 || MESHCORE_FONT_DEFLATE)
