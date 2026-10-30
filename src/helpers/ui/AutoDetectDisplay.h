#pragma once

#include "SSD1306Display.h"

// Compatibility with upstream's driver name. OLED_AUTO_DETECT selects the
// shared backend, including saved controller overrides, rotation and one
// framebuffer. RAK profiles retain SSD1306Display for existing size accounting.
using AutoDetectDisplay = SSD1306Display;
