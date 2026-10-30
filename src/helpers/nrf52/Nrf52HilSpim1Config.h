#pragma once

// Private physical-qualification candidate. All ordinary recipes retain their
// existing controller, clock, and byte-at-a-time transport.
#ifndef MC_NRF52_HIL_SPIM1_RADIO
#define MC_NRF52_HIL_SPIM1_RADIO 0
#endif
#if MC_NRF52_HIL_SPIM1_RADIO != 0 && MC_NRF52_HIL_SPIM1_RADIO != 1
#error "nRF52 HIL SPIM1 radio flag must be 0 or 1"
#endif

#if MC_NRF52_HIL_SPIM1_RADIO
#if !defined(NRF52_PLATFORM) || !defined(NRF52840_XXAA)
#error "nRF52 HIL SPIM1 radio requires the nRF52840 core"
#endif
#if (defined(RAK_WISMESH_TAG) + defined(HELTEC_TOWER_V2)) != 1
#error "nRF52 HIL SPIM1 radio supports only RAK WisMesh Tag or MeshTower V2"
#endif
#if !defined(MC_NRF52_HIL_SPIM1_BOUND) || MC_NRF52_HIL_SPIM1_BOUND != 1
#error "nRF52 HIL SPIM1 radio requires its private SDK binding script"
#endif
#if defined(ETHERNET_ENABLED) || defined(ENV_PIN_SDA) || defined(ENV_PIN_SCL)
#error "nRF52 HIL SPIM1 radio has an unreviewed Ethernet or secondary I2C owner"
#endif
#if defined(SPI_32MHZ_INTERFACE) && SPI_32MHZ_INTERFACE != 0
#error "nRF52 HIL SPIM1 radio must preserve SPI1 on SPIM2"
#endif
#if defined(NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED) && NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED
#error "nRF52 HIL SPIM1 radio must not enable the SPIM3 protected-register workaround"
#endif
#if defined(MC_XIAO_NRF52_HIL_FAST_SPI) && MC_XIAO_NRF52_HIL_FAST_SPI
#error "nRF52 HIL SPIM1 and XIAO SPI candidates are separate"
#endif
#if defined(NRFX_H__) || defined(NRFX_SPIM_H__)
#error "nRF52 HIL SPIM1 configuration must precede nrfx driver headers"
#endif

// This file is force-included in every C and C++ translation unit, including
// SPI.cpp and nrfx_spim.c. The original guard keeps later includes from
// resetting the configuration and changing driver instance indices.
#include <nrfx_config.h>
#if NRFX_SPIM0_ENABLED != 0 || NRFX_SPIM1_ENABLED != 0 || NRFX_SPIM2_ENABLED != 1 || NRFX_SPIM3_ENABLED != 1
#error "nRF52 HIL SPIM1 radio requires the reviewed SDK controller configuration"
#endif
#if (defined(NRFX_TWIM1_ENABLED) && NRFX_TWIM1_ENABLED) || (defined(NRFX_TWI1_ENABLED) && NRFX_TWI1_ENABLED) || (defined(NRFX_TWIS1_ENABLED) && NRFX_TWIS1_ENABLED) || NRFX_SPIS1_ENABLED
#error "nRF52 HIL SPIM1 radio cannot share an enabled nrfx I2C or SPI slave driver"
#endif
#undef NRFX_SPIM1_ENABLED
#define NRFX_SPIM1_ENABLED 1
#undef NRFX_TWIM1_ENABLED
#define NRFX_TWIM1_ENABLED 0
#undef NRFX_TWI1_ENABLED
#define NRFX_TWI1_ENABLED 0
#undef NRFX_TWIS1_ENABLED
#define NRFX_TWIS1_ENABLED 0
#endif
