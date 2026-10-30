#pragma once

#ifndef UI_POCKET_GUI
  #if defined(HELTEC_MESH_POCKET) && defined(COMPANION_RADIO_FULL)
    #define UI_POCKET_GUI 1
  #else
    #define UI_POCKET_GUI 0
  #endif
#endif

#if UI_POCKET_GUI && !(defined(HELTEC_MESH_POCKET) && defined(COMPANION_RADIO_FULL))
  #error "The Pocket GUI requires MeshPocket Full Companion"
#endif

#if UI_POCKET_GUI
  #ifndef UI_MSG_PREVIEW_SIZE
    #define UI_MSG_PREVIEW_SIZE 170
  #endif
  #ifndef MESH_COMPANION_SCREEN_STARTUP_BYTES
    #define MESH_COMPANION_SCREEN_STARTUP_BYTES 12288
  #endif
#endif
