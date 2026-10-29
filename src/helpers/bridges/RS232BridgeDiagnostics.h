#pragma once

#include "RS232Heartbeat.h"
#include <string.h>

namespace mesh {
namespace bridge {
namespace rs232diag {

// Observation belongs to the bridge object, not persistent preferences. Soft
// UART stop/start keeps counters; resetstats, object replacement or reboot does
// not. No receive callback, heap allocation or packet-pool entry is involved.
struct RxStats {
  uint32_t bytes = 0, frames = 0, checksum_bad = 0, length_bad = 0;
  uint32_t packet_bad = 0, noise = 0, timeout = 0, pool_wait = 0;
  uint32_t filtered = 0, duplicate = 0, delivered = 0;
};
struct TxStats {
  uint32_t requested = 0, queued = 0, sent = 0, bytes = 0;
  uint32_t stalls = 0, short_writes = 0, busy = 0, stopped = 0;
  uint32_t filtered = 0, duplicate = 0, oversize = 0;
};
struct ProbeStats {
  uint32_t queued = 0, sent = 0, failed = 0, received = 0, bad = 0;
  uint32_t last_tx_nonce = 0, last_rx_nonce = 0;
};
enum class Error : uint8_t { None, Pins, Driver, TestStopped, TestBusy, TestTimeout };
struct Stats {
  RxStats rx;
  TxStats tx;
  ProbeStats probe;
  Error error = Error::None;
};
static_assert(sizeof(Stats) <= 128, "RS232 diagnostics must keep bounded storage");

inline void increment(uint32_t& value) { if (value != UINT32_MAX) ++value; }
inline void add(uint32_t& value, size_t amount) {
  const uint32_t room = UINT32_MAX - value;
  value = amount >= room ? UINT32_MAX : value + static_cast<uint32_t>(amount);
}
inline const char* errorName(Error error) {
  switch (error) {
    case Error::None: return "none";
    case Error::Pins: return "pins";
    case Error::Driver: return "driver";
    case Error::TestStopped: return "test.stopped";
    case Error::TestBusy: return "test.busy";
    case Error::TestTimeout: return "test.timeout";
  }
  return "unknown";
}

// Same fixed, zero-length control envelope as the heartbeat, with its own
// versioned opcode. Every body byte is ASCII, so legacy parsers which reject
// length zero cannot find a new C0 3E magic word in the body. Existing heartbeat
// decoders reject DG1T. The probe never proves heartbeat liveness or identity.
// Body: DG1T, nonce[8 hex], reserved[32 zeroes], Fletcher16[4 hex].
static constexpr size_t BodySize = rs232heartbeat::BODY_SIZE;
static constexpr size_t FrameSize = rs232heartbeat::FRAME_SIZE;
inline bool isProbeCandidate(const uint8_t* body) {
  return body && body[0] == 'D' && body[1] == 'G';
}
inline bool encodeProbe(uint8_t* body, size_t capacity, uint32_t nonce) {
  if (!body || capacity < BodySize) return false;
  body[0] = 'D'; body[1] = 'G'; body[2] = '1'; body[3] = 'T';
  rs232heartbeat::writeHex(body + 4, nonce, 8);
  memset(body + 12, '0', 32);
  rs232heartbeat::writeHex(body + 44, rs232heartbeat::checksum(body, 44), 4);
  return true;
}
inline bool decodeProbe(const uint8_t* body, size_t size, uint32_t& nonce) {
  if (!body || size != BodySize || !isProbeCandidate(body)
      || body[2] != '1' || body[3] != 'T') return false;
  for (size_t i = 12; i < 44; ++i) if (body[i] != '0') return false;
  uint64_t parsed, checksum;
  if (!rs232heartbeat::readHex(body + 4, 8, parsed)
      || !rs232heartbeat::readHex(body + 44, 4, checksum)
      || checksum != rs232heartbeat::checksum(body, 44)) return false;
  nonce = static_cast<uint32_t>(parsed);
  return true;
}

} // namespace rs232diag
} // namespace bridge
} // namespace mesh
