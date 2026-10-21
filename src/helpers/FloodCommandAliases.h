#pragma once

#include <stddef.h>
#include <string.h>

namespace mesh {
namespace cli {

// Return the untouched argument suffix. Aliases do not expand the caller's
// bounded command buffer or change the bytes covered by a fleet signature.
inline const char* floodCommandArguments(const char* command, const char* family) {
  if (!command || !family) return nullptr;
  const size_t length = strlen(family);
  if (strncmp(command, family, length) == 0
      && (command[length] == 0 || command[length] == ' ' || command[length] == '.'))
    return command + length;

  const char* name = strchr(family, ' ');
  if (!name) return nullptr;
  const size_t verb_length = size_t(++name - family);
  if (strncmp(command, family, verb_length) != 0) return nullptr;
  const char* alias = nullptr;
  if (strcmp(name, "flood.rule") == 0) alias = "fr";
  else if (strcmp(name, "flood.moderation") == 0) alias = "fm";
  else if (strcmp(name, "flood.channel.scope") == 0) alias = "fs";
  else if (strcmp(name, "flood.channel.scope.require") == 0) alias = "fsr";
  else if (strcmp(name, "flood.filter.blacklist") == 0) alias = "fb";
  else if (strcmp(name, "flood.advert") == 0) alias = "fa";
  if (!alias) return nullptr;
  const size_t alias_length = strlen(alias);
  const char* key = command + verb_length;
  if (strncmp(key, alias, alias_length) != 0) return nullptr;
  const char* suffix = key + alias_length;
  return *suffix == 0 || *suffix == ' ' || *suffix == '.' ? suffix : nullptr;
}

} // namespace cli
} // namespace mesh
