#include <helpers/MorseRx.h>
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <sys/types.h>
#include <initializer_list>

static size_t total_free = 0, largest_free = 0;
static int reported_free = 0;
static int heap_mode = 0;
static unsigned largest_queries=0;
struct ESPMock { size_t getFreeHeap() const { return total_free; } } ESP;
struct RP2040Mock { int getFreeHeap() const { return reported_free; } } rp2040;
static constexpr int MALLOC_CAP_8BIT = 1;
size_t heap_caps_get_largest_free_block(int) { ++largest_queries; return largest_free; }
int dbgHeapFree() { return reported_free; }
caddr_t _sbrk(int) {
  if (heap_mode == 0) return reinterpret_cast<caddr_t>(-1);
  if (heap_mode == 1) return reinterpret_cast<caddr_t>(UINTPTR_MAX);
  if (heap_mode == 2) {
    return static_cast<caddr_t>(__builtin_frame_address(0)); // simulated heap already at stack
  }
  return reinterpret_cast<caddr_t>(1);
}
struct RadioLibWrapper {
  mesh::MorseRx* _morse_rx=nullptr;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  mesh::MorseRssiTrace* _morse_trace=nullptr;
#endif
  bool canAllocateMorseReceiver() const;
};
@ADMISSION@

int main() {
  RadioLibWrapper driver;
  mesh::MorseRx retained_rx;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  mesh::MorseRssiTrace retained_trace;
  const unsigned states=4;
#else
  const unsigned states=2;
#endif
  for(unsigned existing=0;existing<states;++existing) {
  driver._morse_rx=(existing&1) ? &retained_rx : nullptr;
  const size_t missing_rx=driver._morse_rx ? 0 : sizeof(mesh::MorseRx);
  size_t missing_trace=0;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  driver._morse_trace=(existing&2) ? &retained_trace : nullptr;
  missing_trace=driver._morse_trace ? 0 : sizeof(mesh::MorseRssiTrace);
#endif
  const size_t allocation=missing_rx+missing_trace;
  const size_t contiguous=missing_rx>missing_trace ? missing_rx : missing_trace;
  const size_t required = allocation + 4096U;
#if defined(ESP32_PLATFORM)
  total_free = required - 1; largest_free = contiguous;
  assert(!driver.canAllocateMorseReceiver());
  total_free = required;
  if(contiguous) {
    largest_free = contiguous - 1;
    assert(!driver.canAllocateMorseReceiver());
  }
  largest_queries=0;
  largest_free = contiguous;
  assert(driver.canAllocateMorseReceiver());
  assert(largest_queries==unsigned(contiguous!=0));
#elif defined(NRF52_PLATFORM) || defined(RP2040_PLATFORM)
  for (int count : {-1, 0, int(required) - 1}) {
    reported_free = count; assert(!driver.canAllocateMorseReceiver());
  }
  reported_free = int(required); assert(driver.canAllocateMorseReceiver());
#elif defined(STM32_PLATFORM)
  for (int mode : {0, 1, 2}) { heap_mode = mode; assert(!driver.canAllocateMorseReceiver()); }
  heap_mode = 3; assert(driver.canAllocateMorseReceiver());
#else
  assert(!driver.canAllocateMorseReceiver()); // unknown allocator is never optimistic
#endif
  }
}
