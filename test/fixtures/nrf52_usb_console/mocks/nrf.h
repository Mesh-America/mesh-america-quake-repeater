#pragma once
#include <cstdint>
struct MockNrfUsbd { uint32_t USBPULLUP = 1; };
extern MockNrfUsbd mock_usbd;
#define NRF_USBD (&mock_usbd)
inline void __ISB() {}
inline void __DSB() {}
