#pragma once
#ifndef FLOOD_ADVERT_IRAM_WORD_STORAGE
#define FLOOD_ADVERT_IRAM_WORD_STORAGE 0
#endif
#if FLOOD_ADVERT_IRAM_WORD_STORAGE != 0 && FLOOD_ADVERT_IRAM_WORD_STORAGE != 1
#error "IRAM advert storage must be zero or one"
#endif
#if FLOOD_ADVERT_IRAM_WORD_STORAGE
#if !defined(ESP32_PLATFORM) || !defined(MESHCORE_EXPANDED_PARTITION_PROFILE)
#error "IRAM advert storage requires the qualified ESP32 Full recipe"
#endif
#include <sdkconfig.h>
#if !defined(CONFIG_IDF_TARGET_ESP32) || CONFIG_ESP32_IRAM_AS_8BIT_ACCESSIBLE_MEMORY
#error "IRAM advert storage requires the classic ESP32 word-only physical memory pool"
#endif
#if FLOOD_ADVERT_RTC_FAST_SLOTS || FLOOD_ADVERT_RTC_SLOW_SLOTS
#error "IRAM and RTC advert backends cannot share one table"
#endif
#include <stdlib.h>
#include <stddef.h>
#endif
