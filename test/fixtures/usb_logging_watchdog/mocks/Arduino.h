#pragma once

#include <stddef.h>
#include <stdint.h>

inline uint32_t mock_watchdog_millis = 0;
inline uint32_t millis() { return mock_watchdog_millis; }
class Stream { public: virtual ~Stream() = default; };
