#pragma once

// Keep charger commands and virtual hooks off boards which cannot implement
// them. Small STM32 images have no flash budget for unused charger controls.
#if defined(TBEAM_SUPREME_SX1262) || defined(TBEAM_SX1262) || \
    defined(TBEAM_SX1276) || defined(HELTEC_MESH_SOLAR)
#define MESH_BATTERY_CHARGE_CONTROL 1
#else
#define MESH_BATTERY_CHARGE_CONTROL 0
#endif
