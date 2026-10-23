#pragma once

// Private physical-qualification candidate only. The normal recipes keep
// their existing SPI transport until BLE, radio and storage checks pass.
#ifndef MC_XIAO_NRF52_HIL_FAST_SPI
#define MC_XIAO_NRF52_HIL_FAST_SPI 0
#endif
#if MC_XIAO_NRF52_HIL_FAST_SPI != 0 && MC_XIAO_NRF52_HIL_FAST_SPI != 1
#error "XIAO nRF52 HIL SPI candidate must be 0 or 1"
#endif
#if MC_XIAO_NRF52_HIL_FAST_SPI
#if !defined(NRF52_PLATFORM) || !defined(NRF52840_XXAA) || !defined(XIAO_NRF52)
#error "XIAO HIL SPI candidate requires the nRF52840 XIAO target"
#endif
#if !defined(SPI_32MHZ_INTERFACE) || SPI_32MHZ_INTERFACE != 1
#error "XIAO HIL SPI candidate requires global SPI mapped to SPIM2"
#endif
#if defined(NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED) && NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED
#error "XIAO HIL SPI candidate must not enable the SPIM3 SoftDevice-conflicting workaround"
#endif
#if defined(OTA_SD_STORE) || defined(OTA_RAK15002_SD_CACHE) || defined(ETHERNET_ENABLED)
#error "XIAO HIL SPI candidate has not qualified an additional SD or Ethernet bus owner"
#endif
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
#endif
