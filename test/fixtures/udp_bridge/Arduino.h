#pragma once
#include <stdint.h>
extern uint32_t test_now;
inline uint32_t millis() { return test_now; }
