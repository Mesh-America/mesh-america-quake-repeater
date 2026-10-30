#pragma once

#include <stddef.h>
#include <stdint.h>

namespace mesh {
class MainBoard;
namespace cli {

// Per-CLI, per-boot history. It is not stored in node preferences or on SD.
struct SdCardCLIState {
  bool format_recorded = false;
  bool erase_recorded = false;
  uint32_t format_at = 0;
  uint32_t erase_at = 0;
};

#if defined(NRF52_PLATFORM) && defined(OTA_SD_STORE)
// The role must perform its normal local/remote authorization before dispatch.
// config begins with "sdcard"; command begins with "get " or "set ".
bool handleSdCardSet(SdCardCLIState& state, MainBoard& board,
                     const char* config, char* reply, size_t capacity);
bool handleSdCardGet(SdCardCLIState& state, MainBoard& board,
                     const char* config, char* reply, size_t capacity);
bool handleSdCardCommand(SdCardCLIState& state, MainBoard& board,
                         const char* command, char* reply, size_t capacity);
#endif

} // namespace cli
} // namespace mesh
