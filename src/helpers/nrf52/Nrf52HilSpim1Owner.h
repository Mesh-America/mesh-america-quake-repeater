#pragma once

#include "Nrf52HilSpim1Config.h"

#if MC_NRF52_HIL_SPIM1_RADIO
// variant.h is available here, unlike the globally forced early SDK config.
// Direct-register Wire1 owns the same peripheral and interrupt as SPIM1.
#if !defined(WIRE_INTERFACES_COUNT) || WIRE_INTERFACES_COUNT != 1
#error "nRF52 HIL SPIM1 radio requires a variant with only the primary I2C bus"
#endif
#if !defined(SPI_INTERFACES_COUNT) || SPI_INTERFACES_COUNT < 1 || SPI_INTERFACES_COUNT > 2
#error "nRF52 HIL SPIM1 radio requires the reviewed one- or two-bus SPI variant"
#endif
#if NRFX_SPIM1_ENABLED != 1 || NRFX_TWIM1_ENABLED != 0 || NRFX_TWI1_ENABLED != 0 || NRFX_TWIS1_ENABLED != 0
#error "nRF52 HIL SPIM1 radio lost its global SDK controller configuration"
#endif
#endif
