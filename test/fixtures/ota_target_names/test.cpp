#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "helpers/ota/OtaTargets.h"

using mesh::ota::ota_target_env_name;

int main() {
  unsigned id;
  while (scanf("%x", &id) == 1) {
#if OTA_TARGET_NAME_TABLE && OTA_TARGET_NAME_FRONT_CODED
    char buffer[mesh::ota::OTA_TARGET_ENV_NAME_CAPACITY];
    const char* name = ota_target_env_name(id, buffer, sizeof buffer);
    if (name) {
      const size_t length = strlen(name);
      char exact[mesh::ota::OTA_TARGET_ENV_NAME_CAPACITY];
      assert(ota_target_env_name(id, exact, length + 1) == exact);
      assert(strcmp(name, exact) == 0);
      // A failed or unrelated lookup must not clobber another caller's result.
      char short_buffer[mesh::ota::OTA_TARGET_ENV_NAME_CAPACITY];
      memset(short_buffer, 'X', sizeof short_buffer);
      assert(ota_target_env_name(id, short_buffer, length) == nullptr);
      assert(short_buffer[0] == 0);
      assert(short_buffer[length] == 'X');
      assert(ota_target_env_name(id, nullptr, sizeof buffer) == nullptr);
      assert(ota_target_env_name(id, short_buffer, 0) == nullptr);
      assert(ota_target_env_name(0, short_buffer, sizeof short_buffer) == nullptr);
      assert(short_buffer[0] == 0);
      assert(strcmp(name, exact) == 0);
    }
#else
    // Keep the original one-argument API, including table-disabled/local fallback.
    const char* name = ota_target_env_name(id);
    assert(ota_target_env_name(id, nullptr, 0) == name);
#endif
    puts(name ? name : "?");
  }
  return 0;
}
