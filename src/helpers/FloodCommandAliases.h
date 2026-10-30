#pragma once

#include <stddef.h>
#include <string.h>

namespace mesh {
namespace cli {

inline bool floodCommandBoundary(char c) {
  return c == 0 || c == ' ' || c == '.' || c == '\t' || c == '\r' || c == '\n';
}

// Return the untouched argument suffix. Aliases do not expand the caller's
// bounded command buffer or change the bytes covered by a fleet signature.
inline const char* floodCommandArguments(const char* command, const char* family) {
  if (!command || !family) return nullptr;
  const size_t length = strlen(family);
  if (strncmp(command, family, length) == 0
      && floodCommandBoundary(command[length]))
    return command + length;

  const char* name = strchr(family, ' ');
  if (!name) return nullptr;
  const size_t verb_length = size_t(++name - family);
  if (strncmp(command, family, verb_length) != 0) return nullptr;
  const char* key = command + verb_length;
  struct Alias {
    const char* name;
    const char* short_name;
  };
  static const Alias aliases[] = {
    {"flood.rule", "fr"},
    {"flood.moderation", "fm"},
    {"flood.channel.scope", "fs"},
    {"flood.channel.scope.require", "fsr"},
    {"flood.filter.blacklist", "fb"},
    {"flood.advert", "fa"},
  };
  for (const auto& alias : aliases) {
    if (strcmp(name, alias.name) != 0) continue;
    const size_t alias_length = strlen(alias.short_name);
    if (strncmp(key, alias.short_name, alias_length) != 0) return nullptr;
    const char* suffix = key + alias_length;
    return floodCommandBoundary(*suffix) ? suffix : nullptr;
  }
  return nullptr;
}

} // namespace cli
} // namespace mesh
