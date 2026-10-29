#pragma once

// Frozen production RX methods from RS232Bridge.cpp at
// 015a3e8e05957d3e432c289c2fd48d060d81591e (before heartbeat support).
// Only the class qualifier was changed. Do not teach this parser controls:
// compatibility requires the OLD receiver to ignore every zero-length frame.
class StockBridge : public BridgeBase {
public:
  Stream* _serial;
  uint8_t _rx_buffer[MAX_TRANS_UNIT + 1 + 6]{};
  uint16_t _rx_buffer_pos = 0;
  bool _rx_packet_ready = false;
  static constexpr uint16_t SERIAL_OVERHEAD = 6;
  StockBridge(NodePrefs* prefs, Stream& serial, mesh::PacketManager* mgr)
    : BridgeBase(prefs, mgr, nullptr), _serial(&serial) { _initialized = true; }
  void begin() override { _initialized = true; }
  void end() override { _initialized = false; }
  void sendPacket(mesh::Packet*) override {}
  void onPacketReceived(mesh::Packet* packet) override { handleReceivedPacket(packet); }

  void drainReceivedPackets() {
    if (!_rx_packet_ready) return;
    mesh::Packet* pkt = _mgr->allocNew();
    if (!pkt) return;
    const uint16_t len = (_rx_buffer[2] << 8) | _rx_buffer[3];
    const bool valid = pkt->readFrom(_rx_buffer + 4, len);
    _rx_buffer_pos = 0;
    _rx_packet_ready = false;
    if (valid) onPacketReceived(pkt);
    else _mgr->free(pkt);
  }

  void loop() override {
    if (_initialized == false) return;
    drainReceivedPackets();
    int remaining = _serial->available();
    if (remaining > 512) remaining = 512;
    while (remaining-- > 0 && !_rx_packet_ready) {
      const int value = _serial->read();
      if (value < 0) break;
      const uint8_t b = static_cast<uint8_t>(value);
      if (_rx_buffer_pos < 2) {
        if ((_rx_buffer_pos == 0 && b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) ||
            (_rx_buffer_pos == 1 && b == (BRIDGE_PACKET_MAGIC & 0xFF))) {
          _rx_buffer[_rx_buffer_pos++] = b;
        } else {
          _rx_buffer_pos = 0;
          if (b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) _rx_buffer[_rx_buffer_pos++] = b;
        }
      } else {
        _rx_buffer[_rx_buffer_pos++] = b;
        if (_rx_buffer_pos >= 4) {
          uint16_t len = (_rx_buffer[2] << 8) | _rx_buffer[3];
          if (len == 0 || len > (MAX_TRANS_UNIT + 1)) {
            _rx_buffer_pos = 0;
            continue;
          }
          if (_rx_buffer_pos == len + SERIAL_OVERHEAD) {
            uint16_t received_checksum = (_rx_buffer[4 + len] << 8) | _rx_buffer[5 + len];
            if (validateChecksum(_rx_buffer + 4, len, received_checksum)) {
              _rx_packet_ready = true;
              drainReceivedPackets();
            }
            if (!_rx_packet_ready) _rx_buffer_pos = 0;
          }
        }
      }
    }
    drainReceivedPackets();
  }
};
