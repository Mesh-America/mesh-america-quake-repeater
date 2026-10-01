#pragma once

#include <stdint.h>

// Nordic's SDK SVC wrappers contain assembly without a memory clobber. With
// whole-program optimization, GCC can infer that the wrappers neither read
// nor write the structures passed to the SoftDevice. That assumption is false
// for GAP pairing keys, GATT notifications, and many other supervisor calls.
// Keep each SVC opaque to its callers and declare its memory side effects.
// This header is force-included in nRF52 C and C++ compilation, including the
// framework, before nrf_svc.h defines SVCALL.
#if defined(NRF52_PLATFORM) && defined(__GNUC__) \
    && !defined(SVCALL_AS_NORMAL_FUNCTION) && !defined(SVCALL)
#if __GNUC__ >= 9
#define MESHCORE_SVC_ATTRIBUTES __attribute__((naked, unused, noipa))
#else
#define MESHCORE_SVC_ATTRIBUTES __attribute__((naked, unused, noinline))
#endif

#define SVCALL(number, return_type, signature)                         \
  _Pragma("GCC diagnostic push")                                     \
  _Pragma("GCC diagnostic ignored \"-Wreturn-type\"")                 \
  MESHCORE_SVC_ATTRIBUTES static return_type signature {              \
    __asm volatile ("svc %0\n" "bx r14" : : "I" ((uint16_t)(number)) \
                    : "r0", "memory");                             \
  }                                                                 \
  _Pragma("GCC diagnostic pop")
#endif
