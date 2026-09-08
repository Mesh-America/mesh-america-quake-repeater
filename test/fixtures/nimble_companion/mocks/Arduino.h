#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
inline uint32_t test_millis = 100;
inline unsigned long millis() { return test_millis; }
