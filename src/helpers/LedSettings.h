#pragma once

#include <helpers/IdentityStore.h>
#include <stddef.h>

namespace mesh {
class MainBoard;
namespace leds {

void beginSettings(MainBoard& board, FILESYSTEM* fs);
bool handleCommand(const char* command, char* reply, size_t capacity);

} // namespace leds
} // namespace mesh
