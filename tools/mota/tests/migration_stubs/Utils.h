#pragma once
#include <stdint.h>
#include <stddef.h>
namespace mesh {
class Utils {
public:
  static void sha256(uint8_t *, size_t, const uint8_t *, int);
  static void sha256(uint8_t *, size_t, const uint8_t *, int, const uint8_t *, int);
};
}
