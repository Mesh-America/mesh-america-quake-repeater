#pragma once

#include <helpers/IdentityStore.h>
#include "OLEDDisplayProbe.h"

namespace mesh { namespace ui {

// Separate, checked storage leaves existing node preference layouts unchanged.
// Load before display startup. A saved Auto selection overrides a build override.
bool loadOLEDControllerSettings(FILESYSTEM* fs);

// The mode selected at startup. Saved changes take effect after a restart.
OLEDControllerMode oledControllerMode();

bool handleOLEDControllerCommand(const char* command, char* reply,
                                 size_t reply_size, bool supported);

}}  // namespace mesh::ui
