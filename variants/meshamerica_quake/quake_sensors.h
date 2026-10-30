#pragma once

// Force-included into every Mesh America Quake Repeater translation unit (see -include in
// platformio.ini).
//
// Re-enable the plain BME680 driver for the RAK1906 environmental sensor. Keymind's reduced-sensor
// trim and the RAK3401/RAK4631 base environments both pass -UENV_INCLUDE_BME680 on the command line,
// and PlatformIO emits every -U after every -D, so no -D in platformio.ini can bring it back. A
// forced include is processed after all command-line -D/-U options, so this define wins and no
// Keymind-owned file has to change.
//
// This is the plain Adafruit driver, not Bosch's BSEC: temperature, humidity, pressure and gas
// resistance, read only when telemetry is requested, so it costs no power while idle. (BSEC adds an
// air-quality index but samples continuously; see docs/d7s-integration.md.) The BSEC variant stays
// off: ENV_INCLUDE_BME680_BSEC is still removed by the trim.
#ifndef ENV_INCLUDE_BME680
#define ENV_INCLUDE_BME680 1
#endif
