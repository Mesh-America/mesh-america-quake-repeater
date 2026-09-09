#pragma once

#include <cstdint>

inline bool g_mock_ed25519_verify_result = true;
inline unsigned g_mock_ed25519_verify_calls = 0;

class Ed25519 {
public:
  static bool verify(const uint8_t*, const uint8_t*, const uint8_t*, int) {
    ++g_mock_ed25519_verify_calls;
    return g_mock_ed25519_verify_result;
  }
};
