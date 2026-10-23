#include "SdCardCLI.h"

#if defined(NRF52_PLATFORM) && defined(OTA_SD_STORE)
#include <Arduino.h>
#include <MeshCore.h>
#include <stdlib.h>
#include <string.h>
#include <helpers/CLICommandUtils.h>
#include <helpers/StorageLayout.h>
#include <helpers/ota/OtaContext.h>

namespace mesh {
namespace cli {

static const uint32_t SDCARD_ACTION_COOLDOWN_MILLIS = 5UL * 60UL * 1000UL;

static const char* skipSpacesConst(const char* value) {
  while (*value == ' ' || *value == '\t') ++value;
  return value;
}

static bool sdCardBusAvailable(char* reply, size_t capacity) {
#if defined(OTA_RAK15002_SD_STORE)
  if (mesh::ota::rak4631_ethernet_owns_spi()) {
    mesh::cli::formatError(reply, capacity, "turn Ethernet off before accessing SD");
    return false;
  }
#else
  (void)reply;
  (void)capacity;
#endif
  return true;
}

static void formatSdCardElapsed(char* out, size_t out_len, bool recorded,
                                uint32_t ran_at, uint32_t now) {
  if (!recorded) {
    snprintf(out, out_len, "never");
    return;
  }

  const uint32_t elapsed_secs = (now - ran_at) / 1000UL;
  if (elapsed_secs < 60UL) {
    snprintf(out, out_len, "%lus ago", (unsigned long)elapsed_secs);
  } else if (elapsed_secs < 60UL * 60UL) {
    snprintf(out, out_len, "%lum %lus ago",
             (unsigned long)(elapsed_secs / 60UL),
             (unsigned long)(elapsed_secs % 60UL));
  } else if (elapsed_secs < 24UL * 60UL * 60UL) {
    snprintf(out, out_len, "%luh %lum ago",
             (unsigned long)(elapsed_secs / 3600UL),
             (unsigned long)((elapsed_secs / 60UL) % 60UL));
  } else {
    snprintf(out, out_len, "%lud %luh ago",
             (unsigned long)(elapsed_secs / 86400UL),
             (unsigned long)((elapsed_secs / 3600UL) % 24UL));
  }
}

// Keep the three failure exits shared even with LTO: each must preserve the
// card error before reset cleanup can replace it, then sample the finish time.
static __attribute__((noinline)) bool finishSdCardFailure(
    mesh::ota::OtaContext& context, mesh::ota::OtaStoreSdNrf52& card,
    char* reply, size_t capacity, const char* format) {
  char error[80];
  strncpy(error, card.last_error(), sizeof(error) - 1);
  error[sizeof(error) - 1] = 0;
  context.finishSdCardReset(millis());
  snprintf(reply, capacity, format, error);
  return true;
}

bool handleSdCardSet(SdCardCLIState& state, MainBoard& board,
                     const char* config, char* reply, size_t capacity) {
  if (!config || !reply || capacity == 0
      || strncmp(config, "sdcard", 6) != 0 ||
      (config[6] != 0 && config[6] != ' ')) {
    return false;
  }

  const char* action_args = skipSpacesConst(config + 6);
  bool is_format;
  const char* suffix;
  if (strncmp(action_args, "format", 6) == 0) {
    is_format = true;
    suffix = action_args + 6;
  } else if (strncmp(action_args, "erase", 5) == 0) {
    is_format = false;
    suffix = action_args + 5;
  } else {
    mesh::cli::formatError(reply, capacity, "use set sdcard format|erase [--force]");
    return true;
  }
  const bool force = strcmp(suffix, " --force") == 0;
  if (*suffix && !force) {
    mesh::cli::formatError(reply, capacity, "use set sdcard format|erase [--force]");
    return true;
  }

  const bool recorded = is_format ? state.format_recorded : state.erase_recorded;
  const uint32_t ran_at = is_format ? state.format_at : state.erase_at;
  const char* action = is_format ? "format" : "erase";
  const uint32_t now = millis();
  if (!force && recorded && now - ran_at < SDCARD_ACTION_COOLDOWN_MILLIS) {
    char age[32];
    formatSdCardElapsed(age, sizeof(age), true, ran_at, now);
    snprintf(reply, capacity,
             "Error: SD card %s ran %s; use set sdcard %s --force",
             action, age, action);
    return true;
  }

  if (!sdCardBusAvailable(reply, capacity)) return true;

  // Heap-backed source-only builds may not have an OTA workspace yet. Never
  // dereference it (or start card maintenance) after an allocation failure.
  if (!mesh::ota::ota_acquire_context(reply, capacity)) return true;
  mesh::ota::OtaContext& context = mesh::ota::ota_ctx();
  if (context.apply_pending) {
    mesh::cli::formatError(reply, capacity, "OTA apply is pending");
    return true;
  }
#if defined(OTA_TOWER_AUTO_STORE)
  // Card maintenance must never abandon a fallback update stored internally.
  if (context.fetch_store.usesInternal() &&
      (context.manager.fetchState() != mesh::ota::OtaManager::IDLE ||
       context.fetch_store.staged_size() != 0)) {
    mesh::cli::formatError(reply, capacity, "internal OTA slot is occupied; use ota cancel first");
    return true;
  }
#elif defined(OTA_RAK15002_SD_STORE) && !defined(OTA_SEEDER_ONLY)
  // The optional card is independent of an internal/NOR application fetch
  // or an internal bootloader package. Formatting it must not reset that
  // unrelated receive session or strand its still-pinned staging bytes.
  if (!context.fetch_store.usesSd() &&
      (context.manager.fetchState() != mesh::ota::OtaManager::IDLE ||
       context.fetch_store.staged_size() != 0)) {
    mesh::cli::formatError(reply, capacity, "non-SD OTA slot is occupied; use ota cancel first");
    return true;
  }
#endif

  mesh::ota::OtaStoreSdNrf52& card = context.sdStagingStore();

  // A card-wide destructive operation invalidates the staged SD fetch. First
  // let an archive capture checkpoint and close its shared card handles.
  context.prepareSdCardReset();
  context.manager.reset_session();
  context.manager.want(0);
  context.manager.want_mid(nullptr);
  context.session_started_ms = 0;
  context.prev_fstate = mesh::ota::OtaManager::IDLE;

  if (is_format) {
    if (!card.formatCard(board)) {
      return finishSdCardFailure(context, card, reply, capacity,
                                 "Error: SD card format failed: %s");
    }
    context.finishSdCardReset(millis());
    state.format_recorded = true;
    state.format_at = millis();
    snprintf(reply, capacity, "OK - SD card format complete");
    return true;
  }

  if (!card.eraseCard(board)) {
    return finishSdCardFailure(context, card, reply, capacity,
                               "Error: SD card erase failed: %s");
  }
  state.erase_recorded = true;
  state.erase_at = millis();

  if (!card.formatCard(board)) {
    return finishSdCardFailure(context, card, reply, capacity,
                               "Error: SD card erased but format failed: %s");
  }
  state.format_recorded = true;
  state.format_at = millis();
  context.finishSdCardReset(millis());
  snprintf(reply, capacity, "OK - SD card erase and format complete");
  return true;
}

bool handleSdCardGet(SdCardCLIState& state, MainBoard& board,
                     const char* config, char* reply, size_t capacity) {
  if (!config || !reply || capacity == 0
      || strncmp(config, "sdcard", 6) != 0 ||
      (config[6] != 0 && config[6] != ' ')) {
    return false;
  }

  const char* query = skipSpacesConst(config + 6);
  const uint32_t now = millis();
  if (*query == 0 || strcmp(query, "*") == 0) {
    char format_age[32];
    char erase_age[32];
    formatSdCardElapsed(format_age, sizeof(format_age),
                        state.format_recorded, state.format_at, now);
    formatSdCardElapsed(erase_age, sizeof(erase_age),
                        state.erase_recorded, state.erase_at, now);
    snprintf(reply, capacity, "> format: %s, erase: %s", format_age, erase_age);
  } else if (strcmp(query, "format") == 0 || strcmp(query, "erase") == 0) {
    const bool format = *query == 'f';
    char age[32];
    formatSdCardElapsed(age, sizeof(age),
                        format ? state.format_recorded : state.erase_recorded,
                        format ? state.format_at : state.erase_at, now);
    snprintf(reply, capacity, "> %s: %s", query, age);
  } else if (strcmp(query, "free") == 0) {
    if (!sdCardBusAvailable(reply, capacity)) return true;
    if (!mesh::ota::ota_acquire_context(reply, capacity)) return true;
    uint64_t used_bytes = 0;
    uint64_t free_bytes = 0;
    mesh::ota::OtaStoreSdNrf52& store = mesh::ota::ota_ctx().sdStagingStore();
    if (!store.getSpace(board, used_bytes, free_bytes)) {
      snprintf(reply, capacity, "Error: SD card space query failed: %s",
               store.last_error());
    } else {
      char used[24];
      char free[24];
      mesh::cli::formatStorageBytes(used, sizeof(used), used_bytes);
      mesh::cli::formatStorageBytes(free, sizeof(free), free_bytes);
      snprintf(reply, capacity, "> used: %s, free: %s", used, free);
    }
  } else if (strncmp(query, "ls", 2) == 0 || strncmp(query, "dir", 3) == 0) {
    const bool is_ls = strncmp(query, "ls", 2) == 0;
    const size_t word_len = is_ls ? 2 : 3;
    if (query[word_len] != 0 && query[word_len] != ' ') {
      mesh::cli::formatError(reply, capacity, "use get sdcard ls|dir [page]");
      return true;
    }
    const char* page_arg = skipSpacesConst(query + word_len);
    uint32_t page = 1;
    if (*page_arg) {
      char* end = nullptr;
      unsigned long parsed = strtoul(page_arg, &end, 10);
      if (parsed == 0 || parsed > 65535 || !end || *skipSpacesConst(end) != 0) {
        mesh::cli::formatError(reply, capacity, "use get sdcard ls|dir [page]");
        return true;
      }
      page = parsed;
    }
    if (!sdCardBusAvailable(reply, capacity)) return true;
    if (!mesh::ota::ota_acquire_context(reply, capacity)) return true;
    mesh::ota::OtaStoreSdNrf52& store = mesh::ota::ota_ctx().sdStagingStore();
    if (!store.listFiles(board, (uint16_t)page, reply, capacity)) {
      snprintf(reply, capacity, "Error: SD card list failed: %s", store.last_error());
    }
  } else {
    mesh::cli::formatError(reply, capacity, "use get sdcard [format|erase|free|ls|dir [page]|*]");
  }
  return true;
}

bool handleSdCardCommand(SdCardCLIState& state, MainBoard& board,
                         const char* command, char* reply, size_t capacity) {
  if (!command) return false;
  if (strncmp(command, "get ", 4) == 0)
    return handleSdCardGet(state, board, command + 4, reply, capacity);
  if (strncmp(command, "set ", 4) == 0)
    return handleSdCardSet(state, board, command + 4, reply, capacity);
  return false;
}

} // namespace cli
} // namespace mesh
#endif
