#pragma once

#include "ClientACL.h"
#include <Utils.h>
#include <stdio.h>
#include <string.h>

namespace mesh {
namespace cli {

inline bool isLiveGuest(const ClientInfo& client) {
  if ((client.permissions & PERM_ACL_ROLE_MASK) != PERM_ACL_GUEST) return false;
  uint8_t key_bits = 0, secret_bits = 0;
  for (size_t i = 0; i < PUB_KEY_SIZE; ++i) {
    key_bits |= client.id.pub_key[i];
    secret_bits |= client.shared_secret[i];
  }
  return key_bits != 0 && secret_bits != 0;
}

// Call after the repeater's admin authorization check. One complete public
// key per page leaves room for activity information in a radio CLI reply.
inline bool handleGuestsGet(const ClientACL& acl, const char* command,
                            char* reply, size_t capacity) {
  static const char prefix[] = "get guests";
  const size_t prefix_len = sizeof(prefix) - 1;
  if (command == nullptr || strncmp(command, prefix, prefix_len) != 0) return false;
  const char* arg = command + prefix_len;
  if (*arg && *arg != ' ' && *arg != '\t' && *arg != '\r' && *arg != '\n') return false;
  if (reply == nullptr || capacity == 0) return true;

  while (*arg == ' ' || *arg == '\t') ++arg;
  unsigned page = 1;
  if (*arg >= '0' && *arg <= '9') {
    page = 0;
    do {
      page = page * 10 + unsigned(*arg++ - '0');
      if (page > 65535) break;
    } while (*arg >= '0' && *arg <= '9');
  }
  while (*arg == ' ' || *arg == '\t' || *arg == '\r' || *arg == '\n') ++arg;
  if (*arg || page == 0 || page > 65535) {
    snprintf(reply, capacity, "Err - usage: get guests [page]");
    return true;
  }

  unsigned total = 0;
  for (int i = 0; i < acl.getNumClients(); ++i) {
    if (isLiveGuest(*acl.getClientByIdx(i))) ++total;
  }
  if (total == 0 && page == 1) {
    snprintf(reply, capacity, "Guests: empty");
    return true;
  }
  const unsigned pages = total == 0 ? 1 : total;
  if (page > pages) {
    snprintf(reply, capacity, "Err - guest page range: 1-%u", pages);
    return true;
  }

  unsigned index = 0;
  for (int i = 0; i < acl.getNumClients(); ++i) {
    const auto* client = acl.getClientByIdx(i);
    if (!isLiveGuest(*client) || ++index != page) continue;
    char key[PUB_KEY_SIZE * 2 + 1];
    Utils::toHex(key, client->id.pub_key, PUB_KEY_SIZE);
    const int needed = snprintf(nullptr, 0, "Guests %u/%u (%u)\n%s last=%lu",
                                page, pages, total, key,
                                static_cast<unsigned long>(client->last_activity));
    // A small caller buffer must never turn a complete key into a prefix.
    if (needed < 0 || size_t(needed) >= capacity) {
      snprintf(reply, capacity, "Err - guest reply too small");
    } else {
      snprintf(reply, capacity, "Guests %u/%u (%u)\n%s last=%lu",
               page, pages, total, key,
               static_cast<unsigned long>(client->last_activity));
    }
    return true;
  }
  return true;
}

}  // namespace cli
}  // namespace mesh
