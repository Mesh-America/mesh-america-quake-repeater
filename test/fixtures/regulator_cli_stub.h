#pragma once
#include <cstddef>

// These dispatch fixtures isolate another command family from the regulator
// subsystem. Its real settings, reset and persistence paths have dedicated
// executable tests in test_regulator_settings.py; an unrelated command falls
// through without changing the reply or requiring a board/filesystem adapter.
namespace mesh { namespace power {
inline bool handleRegulatorCommand(const char*, char*, size_t) { return false; }
}}

// LED persistence has its own executable coverage in test_led_settings.py.
// These command-dispatch fixtures likewise leave unrelated LED commands to
// that subsystem instead of requiring a board/filesystem implementation.
namespace mesh { namespace leds {
inline bool handleCommand(const char*, char*, size_t) { return false; }
}}
