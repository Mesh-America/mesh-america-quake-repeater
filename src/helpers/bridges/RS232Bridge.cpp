#include "RS232Bridge.h"
#include "RS232UartUtils.h"

#include <HardwareSerial.h>
#include <stdio.h>

#ifdef WITH_RS232_BRIDGE

#ifdef ESP32
// check_firmware_ram.py reserves this object plus the UART driver's runtime
// allocation even when a combined Full image starts with the UART disabled.
static_assert(sizeof(RS232Bridge) <= 2816, "Update the ESP32 UART heap budget");
#endif
#if defined(NRF52_PLATFORM) && defined(RAK4631_COMBINED_ETHERNET)
// The combined RAK RAM policy reserves this object plus allocator metadata
// and the UART driver's TX semaphore. Its RX/TX arrays are linked globals.
static_assert(sizeof(RS232Bridge) <= 2816, "Update the combined RAK UART heap budget");
#endif

RS232Bridge::RS232Bridge(NodePrefs *prefs, Stream &serial, int16_t rx_pin,
                         int16_t tx_pin, mesh::PacketManager *mgr,
                         mesh::RTCClock *rtc)
    : BridgeBase(prefs, mgr, rtc), _serial(&serial), _rx_pin(rx_pin),
      _tx_pin(tx_pin) {}

namespace rsdiag = mesh::bridge::rs232diag;

void RS232Bridge::begin() {
  _initialized = false;
  resetTransportState();
  BRIDGE_DEBUG_PRINTLN("Initializing at %d baud...\n", _prefs->bridge_baud);
#if defined(ESP32)
  if (!((HardwareSerial *)_serial)->setPins(_rx_pin, _tx_pin)) {
    _stats.error = rsdiag::Error::Pins;
    _debug_dirty = true;
    return;
  }
#elif defined(NRF52_PLATFORM)
  // Tested with RAK_4631 and T114
  // The Adafruit Uart object may already be active on its variant defaults.
  // Stop it before changing pins or the EasyDMA instance can retain the old
  // pin selection and silently receive nothing.
  mesh::bridge::prepareNrfUart(*((Uart *)_serial), _rx_pin, _tx_pin);
#elif defined(RP2040_PLATFORM)
  ((SerialUART *)_serial)->setRX(_rx_pin);
  ((SerialUART *)_serial)->setTX(_tx_pin);
#elif defined(STM32_PLATFORM)
  ((HardwareSerial *)_serial)->setRx(_rx_pin);
  ((HardwareSerial *)_serial)->setTx(_tx_pin);
#else
#error RS232Bridge was not tested on the current platform
#endif
  ((HardwareSerial *)_serial)->begin(_prefs->bridge_baud);

  // Update bridge state
#if defined(ESP32)
  _initialized = static_cast<bool>(*static_cast<HardwareSerial *>(_serial));
#else
  _initialized = true;
#endif
  if (!_initialized) _stats.error = rsdiag::Error::Driver;
  _debug_dirty = true;
}

void RS232Bridge::end() {
  BRIDGE_DEBUG_PRINTLN("Stopping...\n");
  ((HardwareSerial *)_serial)->end();

  // Update bridge state
  _initialized = false;
  resetTransportState();
  _debug_dirty = true;
}

void RS232Bridge::resetTransportState() {
  _rx_buffer_pos = 0;
  _rx_packet_ready = false;
  _rx_pool_blocked = false;
  // Stop/reconfiguration discards pending transport work. As with mesh data,
  // an accepted prefix cannot be classified as peer delivery or non-delivery.
  if (_tx_is_probe && !_probe_timed_out && _tx_size != 0)
    rsdiag::increment(_stats.probe.failed);
  _tx_size = _tx_pos = 0;
  _tx_wire_pending = false;
  _tx_is_ping = false;
  _tx_is_probe = false;
  _probe_timed_out = false;
  _tx_is_data = false;
  _tx_ping_challenge = 0;
  _outstanding_challenge = 0;
  _pong_target = 0;
  _pong_challenge = 0;
  _ping_due = true;
  _partial_suspend_grace = false;
}

void RS232Bridge::setHeartbeatSession(uint64_t session) {
  if (_session == session) return;
  _session = session;
  _challenge_counter = static_cast<uint32_t>(session)
      ^ static_cast<uint32_t>(session >> 32) ^ 0x9E3779B9UL;
  resetTransportState();
  _peer_session = 0;
  _have_ack = false;
  _ack_fresh = false;
  _standby_armed = false;
  _legacy_rx = false;
  _legacy_fresh = false;
  _power.resetPeer(millis());
}

void RS232Bridge::setHeartbeatEnabled(bool enabled) {
  if (enabled && !_heartbeat_enabled) _ping_due = true;
  _heartbeat_enabled = enabled;
  if (!enabled) _standby_armed = false;
  if (!enabled && _tx_is_ping && _tx_pos == 0) {
    // An unsent PING can be withdrawn. A partially emitted frame must finish
    // to preserve framing of later mesh data; passive PONGs remain supported.
    _tx_size = 0;
    _tx_is_ping = false;
    _tx_ping_challenge = 0;
  }
}

uint32_t RS232Bridge::frameAssemblyMs() const {
  const uint32_t baud = _prefs->bridge_baud ? _prefs->bridge_baud : 115200;
  // Ten wire bits per byte (8N1), plus loop scheduling margin. Start-relative,
  // not last-byte-relative: a noise trickle cannot extend an assembly forever.
  uint32_t duration = static_cast<uint32_t>(
      (static_cast<uint64_t>(MAX_SERIAL_PACKET_SIZE) * 10000 + baud - 1) / baud) + 1000;
  if (duration < 1000) duration = 1000;
  if (duration > 3000) duration = 3000;
  return duration;
}

void RS232Bridge::expirePartialReceive(uint32_t now) {
  if (_rx_buffer_pos != 0 && !_rx_packet_ready
      && static_cast<uint32_t>(now - _rx_started) >= frameAssemblyMs()) {
    _rx_buffer_pos = 0;
    rsdiag::increment(_stats.rx.timeout);
    _debug_dirty = true;
  }
}

void RS232Bridge::expireHeartbeatFreshness(uint32_t now) {
  // Freshness expires permanently until real RX refreshes it. Historical
  // negotiation remains separate, so dead updated peers can still rendezvous
  // and an old timestamp cannot appear alive after a full millis() cycle.
  if (_ack_fresh && static_cast<uint32_t>(now - _last_ack) >= _idle_ms) {
    _ack_fresh = false;
  }
  if (_legacy_fresh && static_cast<uint32_t>(now - _last_legacy_rx) >= _idle_ms) {
    _legacy_fresh = false;
  }
}

bool RS232Bridge::txPending(uint32_t now) const {
  return _tx_size != 0 || (_tx_wire_pending
      && !mesh::bridge::rs232heartbeat::due(now, _tx_wire_until));
}

RS232Bridge::PowerAction RS232Bridge::servicePowerPolicy(
    bool allow_standby, uint32_t idle_ms, uint32_t now, bool force_unconfirmed) {
  _idle_ms = idle_ms;
  expireHeartbeatFreshness(now);
  // Historical successful bidirectional negotiation survives a soft UART stop,
  // but a fresh object/session has no such capability. Never stop a stock or
  // never-confirmed peer by default; explicit force mode is for dead settings.
  const bool armed = allow_standby && _heartbeat_enabled
      && (_have_ack || force_unconfirmed);
  _standby_armed = armed;
  expirePartialReceive(now);
  bool partial_blocks = false;
  if (_rx_buffer_pos != 0 && !_rx_packet_ready
      && _power.standbyDue(armed, idle_ms, now)) {
    // One bounded grace period at the inactivity deadline; repeatedly starting
    // malformed headers cannot keep UART awake indefinitely.
    if (!_partial_suspend_grace) {
      _partial_suspend_grace = true;
      _partial_suspend_until = now + frameAssemblyMs();
    }
    partial_blocks = !mesh::bridge::rs232heartbeat::due(now, _partial_suspend_until);
    if (!partial_blocks) _rx_buffer_pos = 0;
  } else if (!_power.standbyDue(armed, idle_ms, now)) {
    _partial_suspend_grace = false;
  }
  return _power.service(armed, idle_ms, now, _initialized,
      _rx_packet_ready || txPending(now) || partial_blocks);
}

void RS232Bridge::completePowerAction(PowerAction action, bool success, uint32_t now) {
  _power.complete(action, success, now);
}

uint32_t RS232Bridge::powerWakeDelayMs(uint32_t now) const {
  return _power.wakeDelay(now);
}

void RS232Bridge::formatHeartbeatStatus(char* out, size_t capacity, uint32_t now) const {
  if (!out || capacity == 0) return;
  const bool confirmed = _ack_fresh && static_cast<uint32_t>(now - _last_ack) < _idle_ms;
  const char* phase = _power.retrying() ? "retrying"
      : _power.suspended() ? "standby" : _power.probing() ? "probing"
      : _initialized ? "active" : "stopped";
  const char* peer = confirmed ? "confirmed" : _legacy_fresh
      && static_cast<uint32_t>(now - _last_legacy_rx) < _idle_ms ? "legacy" : "unknown";
  const uint32_t age = _power.peerAge(now);
  const uint32_t wake = powerWakeDelayMs(now);
  snprintf(out, capacity, "state=%s,peer=%s,age_s=%lu,wake_s=%lu,heartbeat=%s,armed=%s",
      phase, peer, static_cast<unsigned long>(age == UINT32_MAX ? 0 : age / 1000),
      static_cast<unsigned long>(wake == UINT32_MAX ? 0 : (wake + 999) / 1000),
      _heartbeat_enabled ? "on" : "passive", _standby_armed ? "on" : "off");
  out[capacity - 1] = 0;
}

void RS232Bridge::drainTransmit(uint32_t now, bool blocking) {
  expireProbeTransmit(now);
  if (!_initialized || _tx_size == 0) return;
  size_t amount = static_cast<size_t>(_tx_size - _tx_pos);
  if (!blocking) {
    const int available = _serial->availableForWrite();
    if (available <= 0) {
      rsdiag::increment(_stats.tx.stalls); _debug_dirty = true;
      return;
    }
    if (amount > static_cast<size_t>(available)) amount = static_cast<size_t>(available);
  }
  size_t sent = _serial->write(_tx_buffer + _tx_pos, amount);
  if (sent > amount) sent = amount;
  if (sent == 0) {
    rsdiag::increment(_stats.tx.stalls); _debug_dirty = true;
    return;
  }
  if (sent < amount) rsdiag::increment(_stats.tx.short_writes);
  rsdiag::add(_stats.tx.bytes, sent);
  _debug_dirty = true;
  _tx_pos = static_cast<uint16_t>(_tx_pos + sent);
  const uint32_t baud = _prefs->bridge_baud ? _prefs->bridge_baud : 115200;
  uint32_t base = now;
  if (_tx_wire_pending && !mesh::bridge::rs232heartbeat::due(now, _tx_wire_until)) {
    base = _tx_wire_until;
  }
  _tx_wire_until = base + static_cast<uint32_t>((sent * 10000UL + baud - 1) / baud) + 1;
  _tx_wire_pending = true;
  if (_tx_pos == _tx_size) {
    if (_tx_is_probe) rsdiag::increment(_stats.probe.sent);
    if (_tx_is_data) rsdiag::increment(_stats.tx.sent);
    if (_tx_is_ping) {
      _outstanding_challenge = _tx_ping_challenge;
      _outstanding_since = now;
    }
    _tx_size = _tx_pos = 0;
    _tx_is_ping = false;
    _tx_is_probe = false;
    _tx_is_data = false;
  }
}

bool RS232Bridge::queueControl(char opcode, uint64_t target, uint32_t challenge) {
  if (_tx_size != 0 || _session == 0) return false;
  mesh::bridge::rs232heartbeat::Control control;
  control.opcode = opcode;
  control.sender = _session;
  control.target = target;
  control.challenge = challenge;
  if (!mesh::bridge::rs232heartbeat::encode(_tx_buffer + 4, control)) return false;
  _tx_buffer[0] = 0xC0; _tx_buffer[1] = 0x3E;
  _tx_buffer[2] = _tx_buffer[3] = 0;
  _tx_size = mesh::bridge::rs232heartbeat::FRAME_SIZE;
  _tx_pos = 0;
  _tx_is_ping = opcode == 'P';
  _tx_is_probe = false;
  _tx_is_data = false;
  _tx_ping_challenge = challenge;
  return true;
}

void RS232Bridge::serviceHeartbeat(uint32_t now) {
  if (_session == 0 || _tx_size != 0) return;
  if (_pong_target != 0) {
    if (queueControl('A', _pong_target, _pong_challenge)) {
      _pong_target = 0;
      _pong_challenge = 0;
    }
  } else if (_heartbeat_enabled && (_ping_due
      || mesh::bridge::rs232heartbeat::due(now, _next_ping))) {
    ++_challenge_counter;
    if (_challenge_counter == 0) ++_challenge_counter;
    if (queueControl('P', 0, _challenge_counter)) {
      _ping_due = false;
      _next_ping = now + (_power.probing()
          ? mesh::bridge::rs232heartbeat::PROBE_PING_MS
          : mesh::bridge::rs232heartbeat::ACTIVE_PING_MS);
    }
  }
}

void RS232Bridge::handleControl(uint32_t now) {
  if (rsdiag::isProbeCandidate(_rx_buffer + 4)) {
    uint32_t nonce;
    if (rsdiag::decodeProbe(_rx_buffer + 4, rsdiag::BodySize, nonce)) {
      rsdiag::increment(_stats.probe.received);
      _stats.probe.last_rx_nonce = nonce;
    } else rsdiag::increment(_stats.probe.bad);
    _debug_dirty = true;
    // Deliberately do not alter heartbeat, peer timestamps, power policy,
    // PacketManager or duplicate tables. A probe is never echoed or forwarded.
    return;
  }
  mesh::bridge::rs232heartbeat::Control control;
  if (_session == 0 || !mesh::bridge::rs232heartbeat::decode(_rx_buffer + 4, control)
      || control.sender == _session) return;
  if (control.opcode == 'P') {
    // A replayed PING is not peer liveness. Only a fresh challenge response
    // proves bidirectional reachability; replying also supports passive peers.
    _pong_target = control.sender;
    _pong_challenge = control.challenge;
  } else if (control.target == _session && _outstanding_challenge != 0
      && control.challenge == _outstanding_challenge
      && static_cast<uint32_t>(now - _outstanding_since)
          <= mesh::bridge::rs232heartbeat::ACK_MAX_AGE_MS) {
    _outstanding_challenge = 0; // A matching ACK can be consumed only once.
    _peer_session = control.sender;
    _last_ack = now;
    _have_ack = true;
    _ack_fresh = true;
    _power.notePeer(now);
    _partial_suspend_grace = false;
  }
}

void RS232Bridge::drainReceivedPackets() {
  if (!_rx_packet_ready) return;
  mesh::Packet* pkt = _mgr->allocNew();
  if (!pkt) {
    if (!_rx_pool_blocked) {
      rsdiag::increment(_stats.rx.pool_wait); _debug_dirty = true;
    }
    _rx_pool_blocked = true;
    return;
  }
  const uint16_t len = (_rx_buffer[2] << 8) | _rx_buffer[3];
  const bool valid = pkt->readFrom(_rx_buffer + 4, len);
  _rx_buffer_pos = 0;
  _rx_packet_ready = false;
  _rx_pool_blocked = false;
  if (valid) {
    // A cable loopback or replay of our own accepted mesh TX is not peer proof.
    // OTA must still reach the mesh's timed retry/echo policy, but it cannot
    // refresh UART peer liveness merely by reflecting our own transmission.
    const bool seen = _seen_packets.wasSeen(pkt);
    if (pkt->getPayloadType() != PAYLOAD_TYPE_OTA && seen) {
      rsdiag::increment(_stats.rx.duplicate); _debug_dirty = true;
      _mgr->free(pkt);
      return;
    }
    // Legacy traffic proves inbound reachability, not a bidirectional heartbeat.
    // If ordinary data continues after heartbeat replies have stopped, a stock
    // peer may have replaced the negotiated one. Unarm the safe default rather
    // than eventually sleeping that quiet legacy link. A later fresh ACK can
    // immediately restore negotiated capability; force mode remains explicit.
    if (!seen) {
      if (_have_ack && (!_ack_fresh
          || static_cast<uint32_t>(_rx_packet_received_ms - _last_ack)
              > mesh::bridge::rs232heartbeat::ACTIVE_PING_MS
                  + mesh::bridge::rs232heartbeat::ACK_MAX_AGE_MS)) {
        _have_ack = false;
        _peer_session = 0;
      }
      _legacy_rx = true;
      _legacy_fresh = true;
      _last_legacy_rx = _rx_packet_received_ms;
      _power.notePeer(_rx_packet_received_ms);
      _partial_suspend_grace = false;
    }
    onPacketReceived(pkt);
  }
  else {
    rsdiag::increment(_stats.rx.packet_bad); _debug_dirty = true;
    _mgr->free(pkt);
  }
}

void RS232Bridge::loop() {
  // Guard against uninitialized state
  if (_initialized == false) {
    emitDebug();
    return;
  }

  const uint32_t now = millis();
  expireHeartbeatFreshness(now);
  // Let a tail already buffered by the UART complete first. Flash/admin/sensor
  // work can pause the loop beyond the assembly deadline even though the peer
  // transmitted the complete frame on time; expiry before draining would drop
  // valid legacy traffic. A still-incomplete tail expires after bounded work.
  if (_serial->available() == 0) expirePartialReceive(now);
  drainTransmit(now);

  drainReceivedPackets();
  // Snapshot bounded work; a noisy UART must not starve mesh/radio service.
  int remaining = _serial->available();
  if (remaining > 512) remaining = 512;
  while (remaining-- > 0 && !_rx_packet_ready) {
    const int value = _serial->read();
    if (value < 0) break;
    const uint8_t b = static_cast<uint8_t>(value);
    rsdiag::increment(_stats.rx.bytes); _debug_dirty = true;

    if (_rx_buffer_pos < 2) {
      // Waiting for magic word
      if ((_rx_buffer_pos == 0 && b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) ||
          (_rx_buffer_pos == 1 && b == (BRIDGE_PACKET_MAGIC & 0xFF))) {
        _rx_buffer[_rx_buffer_pos++] = b;
        if (_rx_buffer_pos == 1) _rx_started = now;
      } else {
        // Invalid magic byte, reset and start over
        rsdiag::increment(_stats.rx.noise);
        _rx_buffer_pos = 0;
        // Check if this byte could be the start of a new magic word
        if (b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) {
          _rx_buffer[_rx_buffer_pos++] = b;
          _rx_started = now;
        }
      }
    } else {
      // Reading length, payload, and checksum
      _rx_buffer[_rx_buffer_pos++] = b;

      if (_rx_buffer_pos >= 4) {
        uint16_t len = (_rx_buffer[2] << 8) | _rx_buffer[3];

        // Validate length field
        if (len > (MAX_TRANS_UNIT + 1)) {
          rsdiag::increment(_stats.rx.length_bad);
          BRIDGE_DEBUG_PRINTLN("RX invalid length %d, resetting\n", len);
          _rx_buffer_pos = 0; // Invalid length, reset
          continue;
        }

        if (len == 0) {
          // Zero length was invalid in the old mesh parser. The extension body
          // is fixed-size ASCII, so old receivers cannot find C0 3E within it.
          // New receivers resync immediately if a real new frame interrupts it.
          if (_rx_buffer_pos > 4 && b >= 0x80) {
            _rx_buffer_pos = 0;
            if (b == 0xC0) { _rx_buffer[0] = b; _rx_buffer_pos = 1; _rx_started = now; }
          } else if (_rx_buffer_pos == mesh::bridge::rs232heartbeat::FRAME_SIZE) {
            handleControl(now);
            _rx_buffer_pos = 0;
          }
          continue;
        }

        if (_rx_buffer_pos == len + SERIAL_OVERHEAD) { // Full packet received
          uint16_t received_checksum = (_rx_buffer[4 + len] << 8) | _rx_buffer[5 + len];

          if (validateChecksum(_rx_buffer + 4, len, received_checksum)) {
            rsdiag::increment(_stats.rx.frames);
            BRIDGE_DEBUG_PRINTLN("RX, len=%d crc=0x%04x\n", len, received_checksum);
            _rx_packet_ready = true;
            _rx_packet_received_ms = now;
            drainReceivedPackets(); // continue this bounded batch when the pool is available
          } else {
            rsdiag::increment(_stats.rx.checksum_bad);
            BRIDGE_DEBUG_PRINTLN("RX checksum mismatch, rcv=0x%04x\n", received_checksum);
          }
          if (!_rx_packet_ready) _rx_buffer_pos = 0; // Keep a complete valid frame
        }
      }
    }
  }
  drainReceivedPackets();
  expirePartialReceive(now);
  serviceHeartbeat(now);
  drainTransmit(now);
  emitDebug();
}

void RS232Bridge::sendPacket(mesh::Packet *packet) {
  rsdiag::increment(_stats.tx.requested); _debug_dirty = true;
  // Guard against uninitialized state
  if (_initialized == false) {
    rsdiag::increment(_stats.tx.stopped);
    return;
  }

  // First validate the packet pointer
  if (!packet) {
    BRIDGE_DEBUG_PRINTLN("TX invalid packet pointer\n");
    return;
  }

  if (!allowsPacket(packet)) { rsdiag::increment(_stats.tx.filtered); return; }

  // Preserve the legacy data path's blocking UART acceptance/throughput.
  // Finish a partially emitted control/data frame first, never interleave it.
  // A genuine failed/short hardware write is retained for later loop service;
  // only that failure case cannot accept this caller's additional packet.
  drainTransmit(millis(), true);
  if (_tx_size != 0) {
    rsdiag::increment(_stats.tx.busy);
    return; // Never interleave mesh traffic with a partial frame.
  }

  // The mesh's timed OTA retry cache, not the permanent bridge FIFO, owns
  // duplicate suppression for resumable request/data packets.
  const bool ota = packet->getPayloadType() == PAYLOAD_TYPE_OTA;
  if (ota || !_seen_packets.wasSeen(packet)) {
    const int expected = packet->getRawLength();
    if (expected <= 0 || expected > MAX_TRANS_UNIT + 1) {
      rsdiag::increment(_stats.tx.oversize); return;
    }
    uint8_t* buffer = _tx_buffer;
    uint16_t len = packet->writeTo(buffer + 4);

    // Check if packet fits within our maximum payload size
    if (len == 0 || len > (MAX_TRANS_UNIT + 1)) {
      rsdiag::increment(_stats.tx.oversize);
      BRIDGE_DEBUG_PRINTLN("TX packet too large (payload=%d, max=%d)\n", len, MAX_TRANS_UNIT + 1);
      return;
    }

    // Build packet header
    buffer[0] = (BRIDGE_PACKET_MAGIC >> 8) & 0xFF; // Magic high byte
    buffer[1] = BRIDGE_PACKET_MAGIC & 0xFF;        // Magic low byte
    buffer[2] = (len >> 8) & 0xFF;                 // Length high byte
    buffer[3] = len & 0xFF;                        // Length low byte

    // Calculate checksum over the payload
    uint16_t checksum = fletcher16(buffer + 4, len);
    buffer[4 + len] = (checksum >> 8) & 0xFF; // Checksum high byte
    buffer[5 + len] = checksum & 0xFF;        // Checksum low byte

    // Own the complete frame before returning the shared mesh packet. Data
    // uses the original blocking write contract; control-only loop work stays
    // nonblocking. Local UART acceptance is never peer liveness.
    _tx_size = static_cast<uint16_t>(len + SERIAL_OVERHEAD);
    _tx_pos = 0;
    _tx_is_ping = false;
    _tx_is_probe = false;
    _tx_is_data = true;
    rsdiag::increment(_stats.tx.queued);
    // Retain an outgoing OTA hash solely to reject reflected data as UART
    // peer-liveness proof. It never suppresses OTA delivery in either direction.
    _seen_packets.markSeen(packet);
    drainTransmit(millis(), true);

    BRIDGE_DEBUG_PRINTLN("TX, len=%d crc=0x%04x\n", len, checksum);
  } else rsdiag::increment(_stats.tx.duplicate);
}

void RS232Bridge::onPacketReceived(mesh::Packet *packet) {
  handleReceivedPacket(packet);
}

void RS232Bridge::onIngressResult(IngressResult result) {
  switch (result) {
    case IngressResult::Filtered: rsdiag::increment(_stats.rx.filtered); break;
    case IngressResult::Duplicate: rsdiag::increment(_stats.rx.duplicate); break;
    case IngressResult::Queued: rsdiag::increment(_stats.rx.delivered); break;
    case IngressResult::Stopped: break;
  }
  _debug_dirty = true;
}

void RS232Bridge::resetStats() {
  _stats = rsdiag::Stats{};
  _debug_dirty = true;
}

bool RS232Bridge::sendTest(uint32_t nonce) {
  _debug_dirty = true;
  if (!_initialized || _power.suspended() || _power.retrying() || _power.probing()) {
    _stats.error = rsdiag::Error::TestStopped;
    rsdiag::increment(_stats.probe.failed);
    return false;
  }
  const uint32_t now = millis();
  if (txPending(now) || _pong_target != 0 || (_heartbeat_enabled && _session != 0
      && (_ping_due || mesh::bridge::rs232heartbeat::due(now, _next_ping)))) {
    _stats.error = rsdiag::Error::TestBusy;
    rsdiag::increment(_stats.probe.failed);
    return false;
  }
  rsdiag::encodeProbe(_tx_buffer + 4, sizeof(_tx_buffer) - 4, nonce);
  _tx_buffer[0] = 0xC0; _tx_buffer[1] = 0x3E;
  _tx_buffer[2] = _tx_buffer[3] = 0;
  _tx_pos = 0;
  _tx_size = rsdiag::FrameSize;
  _tx_is_ping = _tx_is_data = false;
  _tx_is_probe = true;
  _probe_timed_out = false;
  _probe_deadline = now + frameAssemblyMs();
  rsdiag::increment(_stats.probe.queued);
  _stats.probe.last_tx_nonce = nonce;
  return true;
}

void RS232Bridge::expireProbeTransmit(uint32_t now) {
  if (!_tx_is_probe || _probe_timed_out || _tx_size == 0
      || !mesh::bridge::rs232heartbeat::due(now, _probe_deadline)) return;
  _probe_timed_out = true;
  // An entirely unsent probe can be canceled. Once its header starts, retain
  // the suffix exactly like a partially emitted heartbeat, so even legacy
  // receivers never consume a later mesh header as this control's length/CRC.
  // UART recovery drains only the unsent suffix, never retransmits the prefix.
  if (_tx_pos == 0) {
    _tx_size = 0;
    _tx_is_probe = false;
  }
  rsdiag::increment(_stats.probe.failed);
  _stats.error = rsdiag::Error::TestTimeout;
  _debug_dirty = true;
}

void RS232Bridge::formatStatus(char* out, size_t capacity) const {
  if (!out || capacity == 0) return;
  const char* phase = _power.retrying() ? "retrying" : _power.suspended() ? "standby"
      : _power.probing() ? "probing" : _initialized ? "ready" : "off";
  snprintf(out, capacity,
      "> %s baud=%lu pins=%d/%d src=%s rxpart=%u rxready=%u tx=%u heartbeat=%s last=%s",
      phase, (unsigned long)_prefs->bridge_baud, (int)_rx_pin, (int)_tx_pin,
      _prefs->bridge_pkt_src ? "rx" : "tx", (unsigned)_rx_buffer_pos,
      _rx_packet_ready ? 1U : 0U, (unsigned)(_tx_size - _tx_pos),
      _heartbeat_enabled ? "on" : "passive", rsdiag::errorName(_stats.error));
  out[capacity - 1] = 0;
}

void RS232Bridge::formatStats(const char* page, char* out, size_t capacity) const {
  if (!out || capacity == 0) return;
  const auto& s = _stats;
  if (!page || !page[0]) {
    snprintf(out, capacity, "> rx=%lu mesh=%lu tx=%lu sent=%lu; pages: rx tx drops test",
        (unsigned long)s.rx.frames, (unsigned long)s.rx.delivered,
        (unsigned long)s.tx.queued, (unsigned long)s.tx.sent);
  } else if (strcmp(page, "rx") == 0) {
    snprintf(out, capacity, "> bytes=%lu frames=%lu crc=%lu length=%lu parse=%lu timeout=%lu pool=%lu",
        (unsigned long)s.rx.bytes, (unsigned long)s.rx.frames,
        (unsigned long)s.rx.checksum_bad, (unsigned long)s.rx.length_bad,
        (unsigned long)s.rx.packet_bad, (unsigned long)s.rx.timeout,
        (unsigned long)s.rx.pool_wait);
  } else if (strcmp(page, "tx") == 0) {
    snprintf(out, capacity, "> req=%lu queued=%lu sent=%lu bytes=%lu stall=%lu short=%lu",
        (unsigned long)s.tx.requested, (unsigned long)s.tx.queued,
        (unsigned long)s.tx.sent, (unsigned long)s.tx.bytes,
        (unsigned long)s.tx.stalls, (unsigned long)s.tx.short_writes);
  } else if (strcmp(page, "drops") == 0) {
    snprintf(out, capacity, "> noise=%lu filter=%lu dupe=%lu busy=%lu stopped=%lu txfilter=%lu txdupe=%lu big=%lu",
        (unsigned long)s.rx.noise, (unsigned long)s.rx.filtered,
        (unsigned long)s.rx.duplicate, (unsigned long)s.tx.busy,
        (unsigned long)s.tx.stopped, (unsigned long)s.tx.filtered,
        (unsigned long)s.tx.duplicate, (unsigned long)s.tx.oversize);
  } else if (strcmp(page, "test") == 0) {
    snprintf(out, capacity, "> queued=%lu sent=%lu fail=%lu rx=%lu bad=%lu txid=%08lX rxid=%08lX",
        (unsigned long)s.probe.queued, (unsigned long)s.probe.sent,
        (unsigned long)s.probe.failed, (unsigned long)s.probe.received,
        (unsigned long)s.probe.bad, (unsigned long)s.probe.last_tx_nonce,
        (unsigned long)s.probe.last_rx_nonce);
  } else snprintf(out, capacity, "Error: use get rs232.stats [rx|tx|drops|test]");
  out[capacity - 1] = 0;
}

void RS232Bridge::emitDebug() {
#if defined(ARDUINO)
  if (!mesh::isUsbDebugLoggingEnabled()) { _debug_was_enabled = false; return; }
  if (!_debug_was_enabled) _debug_dirty = true;
  _debug_was_enabled = true;
  const uint32_t now = millis();
  if (!_debug_dirty || static_cast<uint32_t>(now - _debug_last_at) < 1000) return;
  _debug_last_at = now;
  _debug_dirty = false;
  char status[157];
  formatStatus(status, sizeof(status));
#if defined(NRF52_PLATFORM) || MESH_ESP32_USB_CONSOLE_COOPERATIVE
  mesh::nrf52DebugPrintf("RS232: %s rx=%lu mesh=%lu crc=%lu tx=%lu sent=%lu test.rx=%08lX\n",
      status + 2, (unsigned long)_stats.rx.frames, (unsigned long)_stats.rx.delivered,
      (unsigned long)_stats.rx.checksum_bad, (unsigned long)_stats.tx.queued,
      (unsigned long)_stats.tx.sent, (unsigned long)_stats.probe.last_rx_nonce);
#else
  char line[256];
  const int length = snprintf(line, sizeof(line),
      "RS232: %s rx=%lu mesh=%lu crc=%lu tx=%lu sent=%lu test.rx=%08lX\n",
      status + 2, (unsigned long)_stats.rx.frames, (unsigned long)_stats.rx.delivered,
      (unsigned long)_stats.rx.checksum_bad, (unsigned long)_stats.tx.queued,
      (unsigned long)_stats.tx.sent, (unsigned long)_stats.probe.last_rx_nonce);
  if (length > 0 && (size_t)length < sizeof(line)
      && mesh::usbLoggingPort().availableForWrite() >= length)
    mesh::usbLoggingPort().write(reinterpret_cast<const uint8_t*>(line), length);
#endif
#endif
}

#endif
