#pragma once

// Production stock loop() from meshcore-dev/MeshCore at
// bbe54f8c55d5ccaaeb7e6f867a8f19fc8afb57bd. The class qualifier alone is changed
// to keep this executable compatibility reference independent of our driver.
class UpstreamStockBridge : public StockBridge {
public:
  using StockBridge::StockBridge;
  void loop() override;
};

void UpstreamStockBridge::loop() {
  // Guard against uninitialized state
  if (_initialized == false) {
    return;
  }

  while (_serial->available()) {
    uint8_t b = _serial->read();

    if (_rx_buffer_pos < 2) {
      // Waiting for magic word
      if ((_rx_buffer_pos == 0 && b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) ||
          (_rx_buffer_pos == 1 && b == (BRIDGE_PACKET_MAGIC & 0xFF))) {
        _rx_buffer[_rx_buffer_pos++] = b;
      } else {
        // Invalid magic byte, reset and start over
        _rx_buffer_pos = 0;
        // Check if this byte could be the start of a new magic word
        if (b == ((BRIDGE_PACKET_MAGIC >> 8) & 0xFF)) {
          _rx_buffer[_rx_buffer_pos++] = b;
        }
      }
    } else {
      // Reading length, payload, and checksum
      _rx_buffer[_rx_buffer_pos++] = b;

      if (_rx_buffer_pos >= 4) {
        uint16_t len = (_rx_buffer[2] << 8) | _rx_buffer[3];

        // Validate length field
        if (len > (MAX_TRANS_UNIT + 1)) {
          BRIDGE_DEBUG_PRINTLN("RX invalid length %d, resetting\n", len);
          _rx_buffer_pos = 0; // Invalid length, reset
          continue;
        }

        if (_rx_buffer_pos == len + SERIAL_OVERHEAD) { // Full packet received
          uint16_t received_checksum = (_rx_buffer[4 + len] << 8) | _rx_buffer[5 + len];

          if (validateChecksum(_rx_buffer + 4, len, received_checksum)) {
            BRIDGE_DEBUG_PRINTLN("RX, len=%d crc=0x%04x\n", len, received_checksum);
            mesh::Packet *pkt = _mgr->allocNew();
            if (pkt) {
              if (pkt->readFrom(_rx_buffer + 4, len)) {
                onPacketReceived(pkt);
              } else {
                BRIDGE_DEBUG_PRINTLN("RX failed to parse packet\n");
                _mgr->free(pkt);
              }
            } else {
              BRIDGE_DEBUG_PRINTLN("RX failed to allocate packet\n");
            }
          } else {
            BRIDGE_DEBUG_PRINTLN("RX checksum mismatch, rcv=0x%04x\n", received_checksum);
          }
          _rx_buffer_pos = 0; // Reset for next packet
        }
      }
    }
  }
}
