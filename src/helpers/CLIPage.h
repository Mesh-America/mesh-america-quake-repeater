#pragma once

namespace mesh {
namespace cli {

// Empty arguments select page 1. Zero signals invalid decimal page syntax.
inline unsigned parseCliPage(const char* arg) {
  while (*arg == ' ' || *arg == '\t') ++arg;
  unsigned page = 1;
  if (*arg >= '0' && *arg <= '9') {
    page = 0;
    do {
      page = page * 10 + unsigned(*arg++ - '0');
      if (page > 65535) return 0;
    } while (*arg >= '0' && *arg <= '9');
  }
  while (*arg == ' ' || *arg == '\t' || *arg == '\r' || *arg == '\n') ++arg;
  return *arg ? 0 : page;
}

}  // namespace cli
}  // namespace mesh
