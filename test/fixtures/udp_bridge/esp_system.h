#pragma once
#include <stdint.h>
inline uint32_t random_state = 0x1678abcd;
inline uint32_t esp_random() { random_state ^= random_state << 13; random_state ^= random_state >> 17; random_state ^= random_state << 5; return random_state; }
