#pragma once

#ifndef FLOOD_ADVERT_RTC_FAST_SLOTS
#define FLOOD_ADVERT_RTC_FAST_SLOTS 0
#endif
#ifndef FLOOD_ADVERT_RTC_SLOW_SLOTS
#define FLOOD_ADVERT_RTC_SLOW_SLOTS 0
#endif
#if FLOOD_ADVERT_RTC_FAST_SLOTS < 0 || FLOOD_ADVERT_RTC_SLOW_SLOTS < 0
#error "RTC advert-slot counts must not be negative"
#endif

#if FLOOD_ADVERT_RTC_FAST_SLOTS || FLOOD_ADVERT_RTC_SLOW_SLOTS
#if !defined(ESP32_PLATFORM) || !defined(MESHCORE_EXPANDED_PARTITION_PROFILE)
#error "RTC advert history requires a qualified ESP32 Full recipe"
#endif
#include <sdkconfig.h>
#if !defined(CONFIG_IDF_TARGET_ESP32S3) || !CONFIG_ESP_SYSTEM_ALLOW_RTC_FAST_MEM_AS_HEAP
#error "RTC advert history requires byte-accessible retained ESP32-S3 RTC memory"
#endif
#include <esp_attr.h>
#include <stdint.h>
#include <stdlib.h>
#include <type_traits>
#endif
