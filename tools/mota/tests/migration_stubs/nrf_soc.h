#pragma once
#include <stdint.h>

uint32_t sd_power_gpregret_get(uint32_t index, uint32_t *result);
uint32_t sd_power_gpregret_clr(uint32_t index, uint32_t mask);
uint32_t sd_power_gpregret_set(uint32_t index, uint32_t mask);
