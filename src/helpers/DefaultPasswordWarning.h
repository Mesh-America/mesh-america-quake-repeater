#pragma once

#include <stddef.h>
#include <string.h>

namespace mesh {

static constexpr char DEFAULT_PASSWORD_LOGIN_WARNING[] = "CHANGE YOUR PASSWORD";

inline bool defaultAdminPasswordUnchanged(const char* password,
                                          const char* factory_password,
                                          size_t capacity) {
  // Match the same bounded value stored when the role initializes its prefs.
  return password && factory_password && capacity > 1 && password[0]
      && factory_password[0]
      && strncmp(password, factory_password, capacity - 1) == 0;
}

} // namespace mesh
