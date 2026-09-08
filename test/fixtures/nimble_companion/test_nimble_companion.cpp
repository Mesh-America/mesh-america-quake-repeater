#include <helpers/esp32/SerialBLEInterface.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>

using mesh::companion::BluetoothPeerIdentity;
using namespace fake_nimble;

static void reset() {
  NimBLEDevice::deinit(true);
  failure.clear(); calls.clear(); transmitted.clear();
  persisted = true; accept_notification = true; disconnects = 0;
  test_millis = 100;
}

static void test_identity_modes() {
  // The common MAC policy supplies human-order addresses for all four
  // custom/random modes. The actual adapter must hand the controller exactly
  // those bytes in NimBLE order before any advertisement can start.
  const std::array<std::array<uint8_t, 6>, 4> addresses = {{
      {{0xc2, 0x12, 0x34, 0x56, 0x78, 0x9a}},
      {{0xd3, 0xff, 0x00, 0x7e, 0x01, 0x02}},
      {{0xe4, 0x10, 0x20, 0x30, 0x40, 0x50}},
      {{0xf5, 0x11, 0x22, 0x33, 0x44, 0x55}},
  }};
  for (const auto& chosen : addresses) {
    reset();
    SerialBLEInterface interface;
    assert(interface.begin("MeshCore-", "trial", 246810, chosen.data(), true));
    assert(own_type == BLE_OWN_ADDR_RANDOM);
    for (size_t i = 0; i < 6; ++i) assert(address[i] == chosen[5 - i]);
    auto* server = NimBLEDevice::server.get();
    assert(!server->owns_callbacks && !server->auto_advertise);
    assert(!server->advertising.active);
    assert(pin == 246810 && bonding && mitm && sc && io_cap == BLE_HS_IO_DISPLAY_ONLY);
    interface.enable();
    assert(server->advertising.active);
    assert(std::find(calls.begin(), calls.end(), "address-type") <
           std::find(calls.begin(), calls.end(), "advertise"));
    assert(server->advertising.name == "MeshCore-trial");
    assert(server->advertising.service == "6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
    assert(server->callbacks->onPassKeyDisplay() == 246810);
    assert(interface.takePairingRequest());
    assert(!interface.takePairingRequest());
    NimBLEDevice::deinit(true);  // Must never delete the application interface.
  }

  reset();
  own_type = BLE_OWN_ADDR_RANDOM;
  SerialBLEInterface interface;
  assert(interface.begin("MeshCore-", "default", 123456));
  assert(own_type == BLE_OWN_ADDR_PUBLIC);
  assert(std::find(calls.begin(), calls.end(), "address") == calls.end());
  NimBLEDevice::deinit(true);
}

static void test_startup_failures() {
  const uint8_t custom[] = {0xc2, 0x12, 0x34, 0x56, 0x78, 0x9a};
  for (const char* step : {"clear-bonds", "address", "address-type", "server", "service", "tx", "rx"}) {
    reset(); failure = step;
    SerialBLEInterface interface;
    assert(!interface.begin("MeshCore-", "trial", 123456, custom, true));
    assert(!initialized && !NimBLEDevice::server);
    assert(std::find(calls.begin(), calls.end(), "advertise") == calls.end());
    failure.clear();
    assert(interface.begin("MeshCore-", "trial", 123456, custom, true));
    for (size_t i = 0; i < 6; ++i) assert(address[i] == custom[5 - i]);
    NimBLEDevice::deinit(true);
  }
  reset();
  SerialBLEInterface interface;
  const uint8_t invalid[] = {0x44, 1, 2, 3, 4, 5};
  assert(!interface.begin("MeshCore-", "trial", 123456, invalid));
  assert(calls.empty());
}

static void authenticate(SerialBLEInterface& interface, NimBLEConnInfo& info) {
  auto* server = NimBLEDevice::server.get();
  server->connected = true;
  server->callbacks->onConnect(server, info);
  server->callbacks->onAuthenticationComplete(info);
  uint8_t discarded[MAX_FRAME_SIZE];
  interface.checkRecvFrame(discarded);
}

static void test_authentication_and_bond_lifecycle() {
  for (unsigned missing = 0; missing < 3; ++missing) {
    reset(); SerialBLEInterface interface;
    assert(interface.begin("MeshCore-", "trial", 123456));
    NimBLEConnInfo info;
    if (missing == 0) info.encrypted = false;
    if (missing == 1) info.authenticated = false;
    if (missing == 2) info.bonded = false;
    authenticate(interface, info);
    assert(!interface.isConnected() && !interface.takeSuccessfulConnection());
    assert(disconnects == 1);
    NimBLEDevice::deinit(true);
  }

  reset(); SerialBLEInterface interface;
  assert(interface.begin("MeshCore-", "trial", 123456, nullptr, false, true));
  interface.enable();
  NimBLEConnInfo info;
  // Check an identity address, not a temporary over-the-air private address.
  info.identity.type = BLE_ADDR_RANDOM;
  info.identity.val[5] = 0xd6;
  authenticate(interface, info);
  assert(interface.isConnected());
  BluetoothPeerIdentity peer;
  persisted = false;
  assert(!interface.takeSuccessfulConnection(&peer));
  persisted = true;
  assert(interface.takeSuccessfulConnection(&peer));
  assert(peer.type == mesh::companion::BLUETOOTH_PEER_ADDRESS_RANDOM);
  for (size_t i = 0; i < 6; ++i) assert(peer.address[i] == info.identity.val[5 - i]);
  assert(!interface.takeSuccessfulConnection(&peer));
  assert(interface.enableBondedOnlyAdvertising(peer));
  assert(allowlisted.type == BLE_ADDR_RANDOM);
  assert(memcmp(allowlisted.val, info.identity.val, 6) == 0);
  auto* server = NimBLEDevice::server.get();
  assert(server->advertising.scan_filter && server->advertising.connect_filter);
  assert(!server->advertising.scan_response && server->advertising.name.empty());
  assert(interface.isConnected());
  NimBLEDevice::deinit(true);

  reset(); SerialBLEInterface rebooted;
  persisted = false;
  assert(rebooted.begin("MeshCore-", "trial", 123456, nullptr, false, false, &peer));
  rebooted.enable();
  assert(!NimBLEDevice::server->advertising.active);
  assert(rebooted.takeBondedOnlyRecovery());
  NimBLEDevice::deinit(true);
}

static void test_real_transport_frames() {
  reset(); SerialBLEInterface interface;
  assert(interface.begin("MeshCore-", "trial", 123456));
  interface.enable();
  NimBLEConnInfo info;
  authenticate(interface, info);
  auto* server = NimBLEDevice::server.get();
  auto* tx = server->service->characteristics[0].get();
  auto* rx = server->service->characteristics[1].get();
  assert(tx->properties & NIMBLE_PROPERTY::READ_AUTHEN);
  assert(rx->properties & NIMBLE_PROPERTY::WRITE_AUTHEN);
  uint8_t frame[MAX_FRAME_SIZE];
  for (size_t i = 0; i < sizeof(frame); ++i) frame[i] = i;
  frame[0] = 0x0d;
  uint8_t received[MAX_FRAME_SIZE] = {};
  assert(interface.writeFrame(frame, sizeof(frame)) == sizeof(frame));
  interface.checkRecvFrame(received);
  assert(transmitted.empty()); // Subscription is still pending.
  tx->callbacks->onSubscribe(tx, info, 1);
  mtu = 23;
  interface.checkRecvFrame(received);
  assert(transmitted.empty()); // Never truncate a full protocol frame.
  mtu = 179;
  accept_notification = false;
  interface.checkRecvFrame(received);
  assert(interface.hasPendingIO() && transmitted.empty());
  test_millis += 61;
  accept_notification = true;
  interface.checkRecvFrame(received);
  assert(transmitted.size() == 1 && transmitted[0].size() == sizeof(frame));
  assert(memcmp(transmitted[0].data(), frame, sizeof(frame)) == 0);
  test_millis += 61;
  interface.checkRecvFrame(received);
  assert(transmitted.size() == 1); // No late-status duplicate.

  rx->setValue(frame, sizeof(frame));
  info.authenticated = false;
  rx->callbacks->onWrite(rx, info);
  assert(interface.checkRecvFrame(received) == 0);
  info.authenticated = true;
  rx->callbacks->onWrite(rx, info);
  assert(interface.checkRecvFrame(received) == sizeof(frame));
  assert(memcmp(frame, received, sizeof(frame)) == 0);
  uint8_t oversized[MAX_FRAME_SIZE + 1] = {};
  rx->setValue(oversized, sizeof(oversized));
  rx->callbacks->onWrite(rx, info);
  assert(interface.checkRecvFrame(received) == 0);
  NimBLEDevice::deinit(true);
}

int main() {
  test_identity_modes();
  test_startup_failures();
  test_authentication_and_bond_lifecycle();
  test_real_transport_frames();
  puts("NimBLE adapter: identity, faults, bonding, stealth and full frames PASS");
}
