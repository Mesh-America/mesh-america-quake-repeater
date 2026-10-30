#pragma once

#include <WiFi.h>
#include <cassert>
#include <cerrno>

#ifndef MSG_DONTWAIT
#define MSG_DONTWAIT 0x40
#endif

// One bounded socket send. Unlike SDK WiFiClient::write(), this never polls or
// advances the mock clock. Scripted negative results inject errno, not bytes.
inline int send(int descriptor, const void* source, size_t size, int flags) {
  const auto found = MockTcp::sockets.find(descriptor);
  if (found == MockTcp::sockets.end()) { errno = EBADF; return -1; }
  const auto socket = found->second.lock();
  if (!socket || !socket->connected) { errno = EPIPE; return -1; }
  ++socket->send_calls;
  socket->last_send_flags = flags;
  assert(flags & MSG_DONTWAIT);
  int result = 0;
  if (!socket->send_results.empty()) {
    result = socket->send_results.front();
    socket->send_results.pop_front();
    if (result < 0) { errno = -result; return -1; }
  } else if (socket->send_error) {
    errno = socket->send_error;
    return -1;
  } else {
    result = static_cast<int>(std::min(size, socket->write_limit));
  }
  const size_t written = std::min(size, static_cast<size_t>(result));
  const auto* bytes = static_cast<const uint8_t*>(source);
  socket->sent.insert(socket->sent.end(), bytes, bytes + written);
  errno = 0;
  return static_cast<int>(written);
}
