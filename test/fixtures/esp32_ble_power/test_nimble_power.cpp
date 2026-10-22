#include <helpers/esp32/SerialBLEInterface.h>
#include <algorithm>
#include <cassert>
#include <cstring>
using namespace fake_nimble;
using mesh::companion::BluetoothPeerIdentity;
static const uint8_t custom[] = {0xc2, 1, 2, 3, 4, 5};
static unsigned suites;

static void reset() {
  failure.clear();
  NimBLEDevice::deinit(true);
  calls.clear(); transmitted.clear(); connection_updates.clear();
  stops = deleted_servers = bond_deletions = disconnects = 0;
  persisted = accept_notification = true;
  test_millis = 100;
}
static void stop(SerialBLEInterface& adapter) {
  adapter.disable();
  test_millis += 1000;
  adapter.servicePowerState();
  assert(!adapter.isEnabled() && !adapter.isPowerTransitionPending());
  assert(!initialized && !NimBLEDevice::server);
}
static void connect(SerialBLEInterface& adapter, NimBLEConnInfo& info) {
  auto* server = NimBLEDevice::server.get();
  server->connected = true;
  server->callbacks->onConnect(server, info);
  server->callbacks->onAuthenticationComplete(info);
  assert(adapter.isConnected());
  uint8_t rx[MAX_FRAME_SIZE]; adapter.checkRecvFrame(rx);
}
static void verify(SerialBLEInterface& adapter) {
  auto* server = NimBLEDevice::server.get();
  assert(adapter.isEnabled() && !adapter.isPowerTransitionPending());
  assert(initialized_name == "MeshCore-fixed");
  assert(server && server->advertising.active);
  assert(server->advertising.name == "MeshCore-fixed");
  assert(server->advertising.service == "6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
  assert(server->displayPairingPasskey() == 246810);
  assert(bonding && mitm && sc && mtu == MAX_FRAME_SIZE + 3);
  assert(own_type == BLE_OWN_ADDR_RANDOM);
  for (unsigned i=0; i<6; ++i) assert(address[i] == custom[5-i]);
  assert(server->service->characteristics.size() == 2);
  assert(server->service->characteristics[0]->properties & NIMBLE_PROPERTY::READ_AUTHEN);
  assert(server->service->characteristics[1]->properties & NIMBLE_PROPERTY::WRITE_AUTHEN);
}
static void initial_saved_off() {
  reset(); SerialBLEInterface a;
  char prefix[] = "MeshCore-", name[] = "fixed";
  uint8_t address_copy[6]; memcpy(address_copy, custom, 6);
  assert(a.begin(prefix, name, 246810, address_copy));
  assert(!a.isEnabled() && a.isPowerTransitionPending());
  a.servicePowerState();
  assert(!initialized && !a.isPowerTransitionPending());
  memset(prefix, 'x', sizeof(prefix)-1); memset(name, 'z', sizeof(name)-1);
  memset(address_copy, 0, sizeof(address_copy));
  a.enable(); verify(a); stop(a); ++suites;
}
static void repeated_cycles_preserve_identity_bonds_and_gatt() {
  reset(); SerialBLEInterface a;
  assert(a.begin("MeshCore-", "fixed", 246810, custom, true));
  for (unsigned i=0; i<100; ++i) {
    a.enable(); verify(a); stop(a);
    assert(bond_deletions == 1 && persisted);
    assert(deleted_servers == i+1);
  }
  ++suites;
}
static void deferred_disconnect_and_quick_on() {
  reset(); SerialBLEInterface a;
  assert(a.begin("MeshCore-", "fixed", 246810, custom)); a.enable();
  NimBLEConnInfo info; connect(a, info);
  auto* original = NimBLEDevice::server.get();
  auto* tx = original->service->characteristics[0].get();
  auto* rx = original->service->characteristics[1].get();
  tx->callbacks->onSubscribe(tx, info, 1);
  const uint8_t reply[] = {29, 'O', 'K'};
  assert(a.writeFrame(reply, sizeof(reply)) == sizeof(reply));
  test_millis += 61; uint8_t frame[MAX_FRAME_SIZE];
  a.checkRecvFrame(frame); // Existing main drains its off-command reply first.
  assert(transmitted.size() == 1 && !a.hasPendingIO());
  a.disable();
  assert(!a.isEnabled() && a.isPowerTransitionPending());
  assert(initialized && NimBLEDevice::server.get() == original && stops == 0);
  assert(disconnects == 1 && !original->advertising.active);
  // Late authentication failure during intentional disconnect must not erase
  // a good saved bond. Late writes/subscriptions cannot repopulate the queue.
  info.authenticated = false;
  original->callbacks->onAuthenticationComplete(info);
  rx->setValue(reply, sizeof(reply)); rx->callbacks->onWrite(rx, info);
  tx->callbacks->onSubscribe(tx, info, 1);
  original->callbacks->onDisconnect(original, info, 0);
  assert(bond_deletions == 0 && !a.hasPendingIO());
  a.enable();
  assert(!a.isEnabled() && a.isPowerTransitionPending());
  original->connected = false;
  test_millis += 999; a.servicePowerState();
  assert(NimBLEDevice::server.get() == original && stops == 0);
  ++test_millis; a.servicePowerState(); verify(a);
  assert(deleted_servers == 1 && bond_deletions == 0);
  stop(a); ++suites;
}
static void failed_stop_keeps_callback_objects_alive() {
  reset(); SerialBLEInterface a;
  assert(a.begin("MeshCore-", "fixed", 246810, custom)); a.enable();
  auto* original = NimBLEDevice::server.get();
  failure = "stop-host"; a.disable();
  assert(!a.isEnabled() && a.isPowerTransitionPending());
  assert(initialized && NimBLEDevice::server.get() == original && deleted_servers == 0);
  unsigned attempts = stops;
  for (unsigned i=0; i<100; ++i) a.servicePowerState();
  assert(stops == attempts); // No tight retry loop or premature deletion.
  a.enable(); assert(!a.isEnabled() && a.isPowerTransitionPending());
  failure.clear(); test_millis += 1000; a.servicePowerState(); verify(a);
  assert(bond_deletions == 0); stop(a); ++suites;
}
static void ignored_controller_teardown_failure_is_retried() {
  for (const char* fault : {"stop-controller", "deinit-controller"}) {
    reset(); SerialBLEInterface a;
    assert(a.begin("MeshCore-", "fixed", 246810, custom)); a.enable();
    auto* original = NimBLEDevice::server.get();
    failure = fault; a.disable();
    // Host says it stopped, but its wrapper silently ignored a live
    // controller. Objects and the sleep gate must remain intact.
    assert(!initialized && controller_state != 0);
    assert(!a.isEnabled() && a.isPowerTransitionPending());
    assert(NimBLEDevice::server.get() == original && deleted_servers == 0);
    a.enable(); assert(!a.isEnabled() && a.isPowerTransitionPending());
    failure.clear(); test_millis += 1000; a.servicePowerState(); verify(a);
    assert(deleted_servers == 1 && bond_deletions == 0);
    stop(a);
  }
  ++suites;
}
static void startup_failures_remain_off_and_recover() {
  for (const char* fault : {"init", "address", "address-type", "server", "service", "tx", "rx", "start-service", "advertise"}) {
    reset(); SerialBLEInterface a;
    assert(a.begin("MeshCore-", "fixed", 246810, custom)); a.enable(); stop(a);
    failure = fault; a.enable();
    assert(!a.isEnabled() && !a.isConnected());
    a.servicePowerState();
    assert(!initialized && !a.isPowerTransitionPending());
    assert(bond_deletions == 0);
    failure.clear(); a.enable(); verify(a); stop(a);
  }
  ++suites;
}
static void stealth_and_recovery_never_reopen_general_advertising() {
  reset(); SerialBLEInterface a;
  BluetoothPeerIdentity peer; peer.type = mesh::companion::BLUETOOTH_PEER_ADDRESS_PUBLIC;
  const uint8_t known[] = {1, 2, 3, 4, 5, 6}; memcpy(peer.address, known, 6);
  assert(a.begin("MeshCore-", "fixed", 246810, custom, false, false, &peer));
  for (unsigned i=0; i<3; ++i) {
    a.enable(); auto& adv = NimBLEDevice::server->advertising;
    assert(adv.active && adv.name.empty() && adv.service.empty());
    assert(adv.scan_filter && adv.connect_filter && !adv.scan_response);
    for (unsigned j=0; j<6; ++j) assert(allowlisted.val[j] == known[5-j]);
    stop(a);
  }
  // A missing stored bond must remain suppressed, including after the
  // application consumes the recovery event and toggles Bluetooth again.
  persisted = false; a.enable();
  assert(a.takeBondedOnlyRecovery());
  assert(!NimBLEDevice::server->advertising.active); stop(a);
  persisted = true; a.enable();
  assert(!NimBLEDevice::server->advertising.active); stop(a); ++suites;
}
int main() {
  initial_saved_off(); repeated_cycles_preserve_identity_bonds_and_gatt();
  deferred_disconnect_and_quick_on(); failed_stop_keeps_callback_objects_alive();
  ignored_controller_teardown_failure_is_retried();
  startup_failures_remain_off_and_recover();
  stealth_and_recovery_never_reopen_general_advertising();
  printf("%u lifecycle suites passed\n", suites);
}
