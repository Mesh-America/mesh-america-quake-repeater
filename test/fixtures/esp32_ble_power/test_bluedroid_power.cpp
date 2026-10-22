#include <helpers/esp32/SerialBLEInterface.h>
#include <cassert>
using namespace fake_bt;
static const uint8_t custom[]={0xc2,1,2,3,4,5};
static unsigned suites;
static void retire_global() {
  delete server; server=nullptr;
  delete fake_advertising; fake_advertising=nullptr;
  uuid_adds=0;
}
static void stopped(SerialBLEInterface& a) {
  a.disable(); test_millis+=1000; a.servicePowerState();
  assert(!a.isEnabled() && !a.isPowerTransitionPending());
  assert(controller==ESP_BT_CONTROLLER_STATUS_IDLE);
  assert(host==ESP_BLUEDROID_STATUS_UNINITIALIZED);
  assert(services==0 && characteristics==0 && descriptors==0);
#ifdef TEST_BLE_OWNED_SERVER
  assert(servers==0);
#else
  assert(servers==1); // Valid static library callback target, retired on next init.
#endif
}
static void good(SerialBLEInterface& a) {
  assert(a.isEnabled() && !a.isPowerTransitionPending());
  assert(servers==1 && services==1 && characteristics==2 && descriptors==1);
  assert(name=="MeshCore-legacy" && pin==246810);
  assert(memcmp(address,custom,6)==0 && fake_advertising->active);
}
static void repeated_cycles() {
  SerialBLEInterface a; assert(a.begin("MeshCore-","legacy",246810,custom));
  // Test initial saved-off as well as all subsequent live toggles.
  stopped(a);
  for(unsigned i=0;i<100;++i) {
    a.enable(); good(a); assert(bond_deletions==0); stopped(a);
#ifndef TEST_BLE_OWNED_SERVER
    assert(uuid_adds==1); // Reused static advertiser must not grow forever.
#endif
  }
  retire_global(); ++suites;
}
static void partial_stop_failures_and_late_callbacks() {
  for(const char* fault : {"stop-host","deinit-host","stop-controller","deinit-controller"}) {
    SerialBLEInterface a; assert(a.begin("MeshCore-","legacy",246810,custom)); a.enable(); good(a);
    auto* original=server; original->connected=true;
    esp_ble_gatts_cb_param_t connection;
    original->callbacks->onConnect(original,&connection);
    BLEDevice::security->onAuthenticationComplete(esp_ble_auth_cmpl_t{});
    assert(a.isConnected());
    a.disable(); assert(!a.isEnabled() && a.isPowerTransitionPending());
    assert(server==original && services==1 && characteristics==2);
    original->connected=false;
    failure=fault; test_millis+=1000; a.servicePowerState();
    assert(a.isPowerTransitionPending() && server==original && services==1);
    esp_ble_auth_cmpl_t failed; failed.success=false;
    BLEDevice::security->onAuthenticationComplete(failed);
    assert(bond_deletions==0);
    a.enable(); assert(!a.isEnabled() && a.isPowerTransitionPending());
    failure.clear(); test_millis+=1000; a.servicePowerState(); good(a); stopped(a); retire_global();
  }
  ++suites;
}
static void startup_failures() {
  for(const char* fault : {"init","server","service","tx","rx"}) {
    SerialBLEInterface a; assert(a.begin("MeshCore-","legacy",246810,custom)); a.enable(); stopped(a);
    failure=fault; a.enable();
    assert(!a.isEnabled() && !a.isConnected()); a.servicePowerState();
    assert(!a.isPowerTransitionPending());
    assert(services==0 && characteristics==0 && descriptors==0);
    failure.clear(); a.enable(); good(a); stopped(a); retire_global();
  }
  ++suites;
}
int main() {
  repeated_cycles(); partial_stop_failures_and_late_callbacks(); startup_failures();
  // The legacy library deliberately retains its static server/advertiser
  // until replacement. Release the final objects after the host has stopped.
  delete server; server=nullptr;
  delete fake_advertising; fake_advertising=nullptr;
  assert(servers==0 && services==0 && characteristics==0 && descriptors==0);
  printf("%u lifecycle suites passed\n",suites);
}
