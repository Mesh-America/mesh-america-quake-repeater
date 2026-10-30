#pragma once

#include <stddef.h>
#include <stdlib.h>

namespace mesh {

// Compact iterative heapsort avoids the general qsort implementation on
// flash-constrained STM32/nRF52 boards. It retains O(n log n) comparison work
// without recursion or dynamic storage, including the nRF52 contact tables.
// As with qsort, equally ranked items have no guaranteed tie order.
// Callers provide an array of count trivially-copyable objects of width bytes.
#if defined(STM32_PLATFORM) || defined(NRF52_PLATFORM)
#if defined(__GNUC__) && !defined(__clang__)
__attribute__((noinline, noclone))
#elif defined(__clang__)
__attribute__((noinline))
#endif
inline void sortSmallTable(void* items, size_t count, size_t width,
                           int (*compare)(const void*, const void*)) {
  if (count < 2 || !width) return;
  auto* bytes = static_cast<unsigned char*>(items);
  const auto swapRecords = [width](unsigned char* first, unsigned char* second) {
    for (size_t i = 0; i < width; ++i) {
      const unsigned char temporary = first[i];
      first[i] = second[i];
      second[i] = temporary;
    }
  };
  size_t parent = count / 2, remaining = count;
  for (;;) {
    size_t root = 0;
    if (parent) {
      root = --parent;
    } else {
      if (--remaining == 0) return;
      swapRecords(bytes, bytes + remaining * width);
    }
    // First build a maximum heap from its last parent toward the root, then
    // move each maximum to the sorted suffix and restore the shortened heap.
    while (root < remaining / 2) {
      size_t child = root * 2 + 1;
      auto* child_record = bytes + child * width;
      if (child + 1 < remaining && compare(child_record, child_record + width) < 0) {
        ++child;
        child_record += width;
      }
      auto* root_record = bytes + root * width;
      if (compare(root_record, child_record) >= 0) break;
      swapRecords(root_record, child_record);
      root = child;
    }
  }
}
#else
inline void sortSmallTable(void* items, size_t count, size_t width,
                           int (*compare)(const void*, const void*)) {
  if (count < 2 || !width) return;
  qsort(items, count, width, compare);
}
#endif

}  // namespace mesh
