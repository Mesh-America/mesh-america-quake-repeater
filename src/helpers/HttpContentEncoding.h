#pragma once

#include <stddef.h>
#include <string.h>

namespace mesh {
namespace http {

inline bool encodingTokenEquals(const char* first, const char* last, const char* token) {
  while (first != last && *token) {
    char c = *first++;
    if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    if (c != *token++) return false;
  }
  return first == last && *token == 0;
}

inline void trimEncodingToken(const char*& first, const char*& last) {
  while (first != last && (*first == ' ' || *first == '\t')) ++first;
  while (first != last && (last[-1] == ' ' || last[-1] == '\t')) --last;
}

// A missing header permits any coding (RFC 9110). An empty header requests
// identity only. An explicit gzip preference takes precedence over '*'.
inline bool acceptsGzip(const char* header) {
  if (!header) return true;
  bool wildcard = false;
  bool explicit_gzip = false;
  bool gzip_allowed = false;
  const char* item = header;
  while (*item) {
    const char* end = strchr(item, ',');
    if (!end) end = item + strlen(item);
    const char* semi = static_cast<const char*>(memchr(item, ';', end - item));
    const char* first = item;
    const char* last = semi ? semi : end;
    trimEncodingToken(first, last);
    const bool gzip = encodingTokenEquals(first, last, "gzip");
    const bool star = encodingTokenEquals(first, last, "*");
    bool allowed = true;
    for (const char* param = semi; param && param != end;) {
      first = param + 1;
      param = static_cast<const char*>(memchr(first, ';', end - first));
      last = param ? param : end;
      trimEncodingToken(first, last);
      const char* equal = static_cast<const char*>(memchr(first, '=', last - first));
      if (!equal) continue;
      const char* key_end = equal;
      trimEncodingToken(first, key_end);
      if (!encodingTokenEquals(first, key_end, "q")) continue;
      first = equal + 1;
      trimEncodingToken(first, last);
      // qvalue is 0 or 1 with at most three fractional digits; do not let
      // malformed parameters accidentally enable a compressed response.
      allowed = false;
      if (first == last || (*first != '0' && *first != '1')) continue;
      const bool one = *first++ == '1';
      bool nonzero = one;
      bool valid = true;
      if (first != last) {
        if (*first++ != '.' || last - first > 3) valid = false;
        while (first != last) {
          if (*first < '0' || *first > '9' || (one && *first != '0')) valid = false;
          if (*first != '0') nonzero = true;
          ++first;
        }
      }
      allowed = valid && nonzero;
    }
    if (gzip) { explicit_gzip = true; gzip_allowed = allowed; }
    if (star) wildcard = allowed;
    item = *end ? end + 1 : end;
  }
  return explicit_gzip ? gzip_allowed : wildcard;
}

}  // namespace http
}  // namespace mesh
