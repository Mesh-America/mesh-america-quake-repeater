#pragma once
#include <stddef.h>

// Scheduling tests control the digest to exercise the no-op branch, then
// stop at the EndF lookup before any destructive hardware operation.
class SHA256 {
public:
  void reset();
  void update(const void *, size_t);
  void finalize(void *, size_t);
};
