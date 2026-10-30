#pragma once

// Private role-transition safety only. Ordinary firmware always loads its
// saved frequency, and no startup override is persisted by this helper.
#ifndef MESH_HIL_COMPANION_STARTUP_FREQ_MHZ
#define MESH_HIL_COMPANION_STARTUP_FREQ_MHZ 0
#endif

#if MESH_HIL_COMPANION_STARTUP_FREQ_MHZ != 0 && MESH_HIL_COMPANION_STARTUP_FREQ_MHZ != 917
#error "Companion HIL startup frequency must be disabled or exactly 917 MHz"
#endif

#if MESH_HIL_COMPANION_STARTUP_FREQ_MHZ
#if !defined(NRF52_PLATFORM) || !defined(NRF52840_XXAA) || !defined(XIAO_NRF52) \
    || !defined(MC_XIAO_NRF52_HIL_FAST_SPI) || MC_XIAO_NRF52_HIL_FAST_SPI != 1
#error "Companion startup frequency override requires the explicit XIAO nRF52840 HIL candidate"
#endif
#ifndef LORA_FREQ
#error "Companion startup override requires an explicit 917 MHz initial radio frequency"
#endif
// The board initializes its radio before MyMesh loads Companion preferences.
// Both the initial radio setup and the later saved-parameter path must agree.
static_assert(static_cast<float>(LORA_FREQ) == 917.0f,
              "Initial radio frequency must also be 917 MHz for this HIL image");

namespace mesh { namespace companion {
inline void applyHilStartupFrequency(float& frequency_mhz) {
  frequency_mhz = static_cast<float>(MESH_HIL_COMPANION_STARTUP_FREQ_MHZ);
}
} } // namespace mesh::companion
#endif
