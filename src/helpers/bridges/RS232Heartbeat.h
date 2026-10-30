#pragma once

#include <stddef.h>
#include <stdint.h>

// Portable wire/power helpers: no Arduino dependency, allocation, mesh packets,
// wall clock, or peer-controlled timing values.
namespace mesh {
namespace bridge {
namespace rs232heartbeat {

static constexpr size_t BODY_SIZE = 48;
static constexpr size_t CHECKSUM_OFFSET = 44;
static constexpr size_t FRAME_SIZE = 4 + BODY_SIZE;
static constexpr uint32_t ACTIVE_PING_MS = 30000;
static constexpr uint32_t PROBE_PING_MS = 1000;
static constexpr uint32_t ACK_MAX_AGE_MS = 5000;
// One long listening window exceeds the other peer's maximum 30 s standby
// plus short probe/round-trip margin. The eighth-window rendezvous therefore
// reconnects two stopped UARTs at arbitrary phases without lucky random jitter
// or assuming that RX bytes can wake a physically ended nRF52 Uart driver.
static constexpr uint32_t STANDBY_MS = 30000;
static constexpr uint32_t SHORT_PROBE_MS = 2000;
static constexpr uint32_t LONG_PROBE_MS = 40000;
static constexpr uint32_t ACTION_RETRY_MS = 5000;
static constexpr uint8_t LONG_PROBE_EVERY = 8;

inline bool due(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

inline uint32_t delayTo(uint32_t now, uint32_t deadline) {
  return due(now, deadline) ? 0 : static_cast<uint32_t>(deadline - now);
}

inline uint16_t checksum(const uint8_t* bytes, size_t length) {
  uint16_t a = 0, b = 0;
  for (size_t i = 0; i < length; ++i) {
    a = static_cast<uint16_t>((a + bytes[i]) % 255);
    b = static_cast<uint16_t>((b + a) % 255);
  }
  return static_cast<uint16_t>((b << 8) | a);
}

inline void writeHex(uint8_t* out, uint64_t value, size_t digits) {
  static const char HEX_DIGITS[] = "0123456789ABCDEF";
  for (size_t i = digits; i != 0; --i) {
    out[i - 1] = static_cast<uint8_t>(HEX_DIGITS[value & 15]);
    value >>= 4;
  }
}

inline bool readHex(const uint8_t* in, size_t digits, uint64_t& value) {
  value = 0;
  for (size_t i = 0; i < digits; ++i) {
    const uint8_t c = in[i];
    uint8_t nibble;
    if (c >= '0' && c <= '9') nibble = static_cast<uint8_t>(c - '0');
    else if (c >= 'A' && c <= 'F') nibble = static_cast<uint8_t>(c - 'A' + 10);
    else return false;
    value = (value << 4) | nibble;
  }
  return true;
}

struct Control {
  uint64_t sender = 0;
  uint64_t target = 0;
  uint32_t challenge = 0;
  char opcode = 0;
};

inline bool encode(uint8_t* body, const Control& control) {
  if (!body || control.sender == 0 || control.challenge == 0
      || (control.opcode != 'P' && control.opcode != 'A')
      || (control.opcode == 'P' && control.target != 0)
      || (control.opcode == 'A' && control.target == 0)) return false;
  body[0] = 'H'; body[1] = 'B'; body[2] = '1';
  body[3] = static_cast<uint8_t>(control.opcode);
  writeHex(body + 4, control.sender, 16);
  writeHex(body + 20, control.target, 16);
  writeHex(body + 36, control.challenge, 8);
  writeHex(body + CHECKSUM_OFFSET, checksum(body, CHECKSUM_OFFSET), 4);
  return true;
}

inline bool decode(const uint8_t* body, Control& control) {
  if (!body || body[0] != 'H' || body[1] != 'B' || body[2] != '1'
      || (body[3] != 'P' && body[3] != 'A')) return false;
  uint64_t sender, target, challenge, crc;
  if (!readHex(body + 4, 16, sender) || !readHex(body + 20, 16, target)
      || !readHex(body + 36, 8, challenge)
      || !readHex(body + CHECKSUM_OFFSET, 4, crc)
      || crc != checksum(body, CHECKSUM_OFFSET)
      || sender == 0 || challenge == 0
      || (body[3] == 'P' && target != 0)
      || (body[3] == 'A' && target == 0)) return false;
  control.sender = sender;
  control.target = target;
  control.challenge = static_cast<uint32_t>(challenge);
  control.opcode = static_cast<char>(body[3]);
  return true;
}

} // namespace rs232heartbeat

class RS232PowerPolicy {
public:
  enum class Action : uint8_t { None, Suspend, Resume };

  void notePeer(uint32_t now) {
    _started = true;
    _last_peer = now;
    _has_peer = true;
    _probing = false;
    _probe_count = 0;
  }

  // Invalidating a session must not trust liveness from the previous session.
  void resetPeer(uint32_t now) {
    _started = true;
    _last_peer = now;
    _has_peer = false;
  }

  bool standbyDue(bool allowed, uint32_t idle_ms, uint32_t now) const {
    if (!allowed || _suspended || _requested != Action::None
        || _retry_action != Action::None) return false;
    return _probing ? rs232heartbeat::due(now, _phase_deadline)
                    : _started && static_cast<uint32_t>(now - _last_peer) >= idle_ms;
  }

  Action service(bool allowed, uint32_t idle_ms, uint32_t now,
                 bool running, bool blocked) {
    if (!_started) {
      _started = true;
      _last_peer = now;
    }
    if (_requested != Action::None) return Action::None;
    if (_retry_action != Action::None) {
      if (!rs232heartbeat::due(now, _retry_deadline)) return Action::None;
      _requested = _retry_action;
      return _requested;
    }
    if (!allowed) {
      _probing = false;
      if (_suspended || !running) _requested = Action::Resume;
    } else if (_suspended) {
      if (rs232heartbeat::due(now, _phase_deadline)) _requested = Action::Resume;
    } else if (!running) {
      _requested = Action::Resume;
    } else if (standbyDue(allowed, idle_ms, now) && !blocked) {
      _requested = Action::Suspend;
    }
    return _requested;
  }

  void complete(Action action, bool success, uint32_t now) {
    if (action == Action::None || action != _requested) return;
    _requested = Action::None;
    if (!success) {
      // A failed physical stop can leave GPS ownership pending although UART
      // is already ended. Finish that same action, never restart prematurely.
      _retry_action = action;
      _retry_deadline = now + rs232heartbeat::ACTION_RETRY_MS;
      return;
    }
    _retry_action = Action::None;
    if (action == Action::Suspend) {
      _suspended = true;
      _probing = false;
      _phase_deadline = now + rs232heartbeat::STANDBY_MS;
    } else {
      const bool was_suspended = _suspended;
      _suspended = false;
      if (was_suspended) {
        _probing = true;
        _probe_count = static_cast<uint8_t>(_probe_count + 1);
        const uint32_t window = _probe_count % rs232heartbeat::LONG_PROBE_EVERY == 0
            ? rs232heartbeat::LONG_PROBE_MS : rs232heartbeat::SHORT_PROBE_MS;
        _phase_deadline = now + window;
      }
    }
  }

  uint32_t wakeDelay(uint32_t now) const {
    if (_requested != Action::None) return 0;
    if (_retry_action != Action::None) return rs232heartbeat::delayTo(now, _retry_deadline);
    if (_suspended || _probing) return rs232heartbeat::delayTo(now, _phase_deadline);
    return UINT32_MAX;
  }

  bool suspended() const { return _suspended; }
  bool probing() const { return _probing; }
  bool hasPeer() const { return _has_peer; }
  bool retrying() const { return _retry_action != Action::None; }
  uint32_t peerAge(uint32_t now) const {
    return _has_peer ? static_cast<uint32_t>(now - _last_peer) : UINT32_MAX;
  }

private:
  uint32_t _last_peer = 0;
  uint32_t _phase_deadline = 0;
  uint32_t _retry_deadline = 0;
  Action _requested = Action::None;
  Action _retry_action = Action::None;
  uint8_t _probe_count = 0;
  bool _started = false;
  bool _has_peer = false;
  bool _suspended = false;
  bool _probing = false;
};

} // namespace bridge
} // namespace mesh
