#pragma once

#include "helpers/bridges/BridgeBase.h"
#include "helpers/bridges/RS232Heartbeat.h"

#include <Stream.h>

#ifdef WITH_RS232_BRIDGE

/**
 * @brief Bridge implementation using RS232/UART protocol for packet transport
 *
 * This bridge enables mesh packet transport over serial/UART connections,
 * allowing nodes to communicate over wired serial links. It implements a simple
 * packet framing protocol with checksums for reliable transfer.
 *
 * Features:
 * - Point-to-point communication over hardware UART
 * - Fletcher-16 checksum for data integrity verification
 * - Magic header for packet synchronization and frame alignment
 * - Duplicate packet detection using SimpleMeshTables tracking
 * - Configurable UART and RX/TX pins selected by the owning runtime
 * - Fixed baud rate at 115200 for consistent timing
 *
 * Packet Structure:
 * [2 bytes] Magic Header (0xC03E) - Used to identify start of RS232Bridge packets
 * [2 bytes] Payload Length - Length of the mesh packet payload
 * [n bytes] Mesh Packet Payload - The actual mesh packet data
 * [2 bytes] Fletcher-16 Checksum - Calculated over the payload for integrity verification
 *
 * The Fletcher-16 checksum is calculated over the mesh packet payload and provides
 * error detection capabilities suitable for serial communication where electrical
 * noise, timing issues, or hardware problems could corrupt data. The checksum
 * validation ensures only valid packets are forwarded to the mesh.
 *
 * Configuration:
 * - Define WITH_RS232_BRIDGE to enable this bridge
 * - The owning role supplies the selected UART and pins to the constructor
 *
 * Platform Support:
 * Different platforms require different pin configuration methods:
 * - ESP32: Uses HardwareSerial::setPins(rx, tx)
 * - NRF52: Uses Uart::setPins(rx, tx)
 * - RP2040: Uses SerialUART::setRX(rx) and SerialUART::setTX(tx)
 * - STM32: Uses HardwareSerial::setRx(rx) and HardwareSerial::setTx(tx)
 */
class RS232Bridge : public BridgeBase {
public:
  /**
   * @brief Constructs an RS232Bridge instance
   *
   * @param prefs Node preferences for configuration settings
   * @param serial The hardware serial port to use
   * @param mgr PacketManager for allocating and queuing packets
   * @param rtc RTCClock for timestamping debug messages
   */
  RS232Bridge(NodePrefs *prefs, Stream &serial, int16_t rx_pin, int16_t tx_pin,
              mesh::PacketManager *mgr, mesh::RTCClock *rtc);

  /**
   * Initializes the RS232 bridge
   *
   * - Configures UART pins based on target platform
   * - Sets baud rate to 115200 for consistent communication
   * - Platform-specific pin configuration methods are used
   */
  void begin() override;

  /**
   * Stops the RS232 bridge
   *
   */
  void end() override;

  /**
   * @brief Main loop handler for processing incoming serial data
   *
   * Implements a state machine for packet reception:
   * 1. Searches for magic header bytes for packet synchronization
   * 2. Reads length field to determine expected packet size
   * 3. Validates packet length against maximum allowed size
   * 4. Receives complete packet payload and checksum
   * 5. Validates Fletcher-16 checksum for data integrity
   * 6. Creates mesh packet and forwards if valid
   */
  void loop() override;

  /**
   * @brief Called when a packet needs to be transmitted over serial
   *
   * Formats the mesh packet with RS232 framing protocol:
   * - Adds magic header for synchronization
   * - Includes payload length field
   * - Calculates Fletcher-16 checksum over payload
   * - Transmits complete framed packet
   * - Uses duplicate detection to prevent retransmission
   *
   * @param packet The mesh packet to transmit
   */
  void sendPacket(mesh::Packet *packet) override;

  /**
   * @brief Called when a complete valid packet has been received from serial
   *
   * Forwards the received packet to the mesh for processing.
   * The packet has already been validated for checksum integrity
   * and parsed successfully at this point.
   *
   * @param packet The received mesh packet ready for processing
   */
  void onPacketReceived(mesh::Packet *packet) override;

  using PowerAction = mesh::bridge::RS232PowerPolicy::Action;

  // The owner supplies a fresh, nonzero boot/object session before begin().
  // This is not a persistent identity or authentication secret.
  void setHeartbeatSession(uint64_t session);
  void setHeartbeatEnabled(bool enabled);
  PowerAction servicePowerPolicy(bool allow_standby, uint32_t idle_ms, uint32_t now,
                                 bool force_unconfirmed = false);
  void completePowerAction(PowerAction action, bool success, uint32_t now);
  uint32_t powerWakeDelayMs(uint32_t now) const;
  void formatHeartbeatStatus(char* out, size_t capacity, uint32_t now) const;
  bool isPowerSuspended() const { return _power.suspended(); }

private:
  /**
   * RS232 Protocol Structure:
   * - Magic header: 2 bytes (packet identification)
   * - Length field: 2 bytes (payload length)
   * - Payload: variable bytes (mesh packet data)
   * - Checksum: 2 bytes (Fletcher-16 over payload)
   * Total overhead: 6 bytes
   */

  /**
   * @brief The total overhead of the serial protocol in bytes.
   * Includes: MAGIC_WORD (2) + LENGTH (2) + CHECKSUM (2) = 6 bytes
   */
  static constexpr uint16_t SERIAL_OVERHEAD = BRIDGE_MAGIC_SIZE + BRIDGE_LENGTH_SIZE + BRIDGE_CHECKSUM_SIZE;

  /**
   * @brief The maximum size of a complete packet on the serial line.
   *
   * This is calculated as the sum of:
   * - MAX_TRANS_UNIT + 1 for the maximum mesh packet size
   * - SERIAL_OVERHEAD for the framing (magic + length + checksum)
   */
  static constexpr uint16_t MAX_SERIAL_PACKET_SIZE = (MAX_TRANS_UNIT + 1) + SERIAL_OVERHEAD;

  /** Hardware serial port interface */
  Stream *_serial;
  int16_t _rx_pin;
  int16_t _tx_pin;

  /** Buffer for building received packets */
  uint8_t _rx_buffer[MAX_SERIAL_PACKET_SIZE];

  // Retain the completed parser buffer while the shared pool is exhausted;
  // unread bytes remain in the UART driver until this frame is delivered.
  bool _rx_packet_ready = false;
  void drainReceivedPackets();

  /** Current position in the receive buffer */
  uint16_t _rx_buffer_pos = 0;

  // Data and control share this owned buffer, so partial UART writes can never
  // interleave frames. It owns bytes, not a mesh::Packet from the shared pool.
  uint8_t _tx_buffer[MAX_SERIAL_PACKET_SIZE];
  uint16_t _tx_size = 0;
  uint16_t _tx_pos = 0;
  uint32_t _tx_wire_until = 0;
  bool _tx_wire_pending = false;
  bool _tx_is_ping = false;
  uint32_t _tx_ping_challenge = 0;

  mesh::bridge::RS232PowerPolicy _power;
  uint64_t _session = 0;
  uint64_t _peer_session = 0;
  uint64_t _pong_target = 0;
  uint32_t _pong_challenge = 0;
  uint32_t _challenge_counter = 0;
  uint32_t _outstanding_challenge = 0;
  uint32_t _outstanding_since = 0;
  uint32_t _next_ping = 0;
  uint32_t _last_ack = 0;
  uint32_t _last_legacy_rx = 0;
  uint32_t _rx_started = 0;
  uint32_t _rx_packet_received_ms = 0;
  uint32_t _partial_suspend_until = 0;
  uint32_t _idle_ms = 300000;
  bool _heartbeat_enabled = true;
  bool _standby_armed = false;
  bool _ping_due = true;
  bool _have_ack = false;
  bool _ack_fresh = false;
  bool _legacy_rx = false;
  bool _legacy_fresh = false;
  bool _partial_suspend_grace = false;

  void resetTransportState();
  void expirePartialReceive(uint32_t now);
  void expireHeartbeatFreshness(uint32_t now);
  uint32_t frameAssemblyMs() const;
  bool txPending(uint32_t now) const;
  void drainTransmit(uint32_t now, bool blocking = false);
  void serviceHeartbeat(uint32_t now);
  bool queueControl(char opcode, uint64_t target, uint32_t challenge);
  void handleControl(uint32_t now);
};

#endif
