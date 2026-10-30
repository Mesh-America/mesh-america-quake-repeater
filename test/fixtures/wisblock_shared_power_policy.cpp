#include <helpers/sensors/WisBlockSharedPowerPolicy.h>
#include <cassert>
#include <cstdint>
#include <type_traits>
#include <initializer_list>

using mesh::gps::WisBlockPeripheralMode;
using mesh::gps::WisBlockSharedPowerPolicy;
using mesh::gps::RadioPower;
using mesh::gps::EthernetPower;
using mesh::gps::ExternalStorage;

static_assert(sizeof(WisBlockSharedPowerPolicy) == 2, "No allocation or added per-board RAM");
static_assert(std::is_trivially_copyable<WisBlockSharedPowerPolicy>::value,
              "The rail policy must not acquire an owning allocation");
static_assert(mesh::gps::wisBlockCompileRailHolds() == EXPECTED_COMPILE_HOLDS,
              "Compile-time radio/PoE dependencies are unconditional holds");

static void expectState(const WisBlockSharedPowerPolicy& policy, bool configured,
                        bool discovery, bool gps, WisBlockPeripheralMode mode,
                        uint8_t holds) {
  assert(policy.isConfigured() == configured);
  assert(policy.discoveryActive() == discovery);
  assert(policy.gpsActive() == gps);
  assert(policy.mode() == mode);
  assert(policy.holds() == holds);
  const bool independently_controllable = configured && !discovery
      && mode == WisBlockPeripheralMode::GpsOnly && holds == 0;
  assert(policy.gpsPowerIndependentlyControllable() == independently_controllable);
  assert(policy.canPowerDown() == (independently_controllable && !gps));
  assert(policy.railEnabled() == !(independently_controllable && !gps));
}

static void bootAndDiscovery() {
  WisBlockSharedPowerPolicy policy;
  expectState(policy, false, true, false, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  // Even an early discovery completion cannot cut power before saved mode is known.
  policy.setDiscoveryActive(false);
  expectState(policy, false, false, false, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  policy.setDiscoveryActive(true);
  policy.setGpsActive(true);
  assert(policy.configure(WisBlockPeripheralMode::GpsOnly));
  expectState(policy, true, true, true, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  policy.setGpsActive(false);
  assert(policy.railEnabled());  // Saved disabled GPS cannot defeat discovery protection.
  policy.setDiscoveryActive(false);
  expectState(policy, true, false, false, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  // Configuration is boot-only: changing a saved mode must not cause a live rail transition.
  assert(!policy.configure(WisBlockPeripheralMode::Shared, ExternalStorage));
  expectState(policy, true, false, false, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  policy.setGpsActive(true);
  expectState(policy, true, false, true, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
  policy.setGpsActive(false);
  policy.setDiscoveryActive(true);  // A subsequent safe probe reacquires its hold.
  assert(policy.railEnabled() && !policy.gpsPowerIndependentlyControllable());
  policy.setDiscoveryActive(false);
  expectState(policy, true, false, false, WisBlockPeripheralMode::GpsOnly,
              EXPECTED_COMPILE_HOLDS);
}

static void everyOwnershipCombination() {
  // External NOR is a physical dependency, independent of user/service enablement.
  // All valid owner unions must survive GPS settings and repeated probes.
  for (uint8_t initial = 0; initial < 8; ++initial) {
    for (uint8_t detected = 0; detected < 8; ++detected) {
      for (uint8_t mode_value = 0; mode_value < 2; ++mode_value) {
        const auto mode = static_cast<WisBlockPeripheralMode>(mode_value);
        WisBlockSharedPowerPolicy policy(initial);
        assert(policy.configure(mode, detected));
        const uint8_t holds = static_cast<uint8_t>(initial | detected | EXPECTED_COMPILE_HOLDS);
        for (unsigned repeat = 0; repeat < 2; ++repeat) {
          for (bool discovery : {false, true}) {
            for (bool gps : {false, true}) {
              policy.setDiscoveryActive(discovery);
              policy.setGpsActive(gps);
              expectState(policy, true, discovery, gps, mode, holds);
              assert(!policy.configure(WisBlockPeripheralMode::GpsOnly, 0));
              expectState(policy, true, discovery, gps, mode, holds);
            }
          }
        }
      }
    }
  }
  WisBlockSharedPowerPolicy storage;
  assert(storage.configure(WisBlockPeripheralMode::GpsOnly, ExternalStorage));
  storage.setDiscoveryActive(false);
  assert(storage.railEnabled() && !storage.canPowerDown());
  assert(!storage.gpsPowerIndependentlyControllable());
  WisBlockSharedPowerPolicy shared;
  assert(shared.configure(WisBlockPeripheralMode::SharedPeripherals));
  shared.setDiscoveryActive(false);
  assert(shared.railEnabled() && !shared.gpsPowerIndependentlyControllable());
}

static void rejectedConfigurationRetainsOwners() {
  WisBlockSharedPowerPolicy policy(RadioPower);
  policy.setGpsActive(true);
  assert(!policy.configure(static_cast<WisBlockPeripheralMode>(2), ExternalStorage));
  expectState(policy, false, true, true, WisBlockPeripheralMode::GpsOnly,
              RadioPower | EXPECTED_COMPILE_HOLDS);
  assert(!policy.configure(static_cast<WisBlockPeripheralMode>(255), 0));
  assert(!policy.configure(WisBlockPeripheralMode::GpsOnly, 0x80));
  expectState(policy, false, true, true, WisBlockPeripheralMode::GpsOnly,
              RadioPower | EXPECTED_COMPILE_HOLDS);
  assert(policy.configure(WisBlockPeripheralMode::GpsOnly, ExternalStorage));
  policy.setGpsActive(false);
  policy.setDiscoveryActive(false);
  expectState(policy, true, false, false, WisBlockPeripheralMode::GpsOnly,
              RadioPower | ExternalStorage | EXPECTED_COMPILE_HOLDS);
  assert(!policy.configure(WisBlockPeripheralMode::Shared, EthernetPower));
  expectState(policy, true, false, false, WisBlockPeripheralMode::GpsOnly,
              RadioPower | ExternalStorage | EXPECTED_COMPILE_HOLDS);
  // A future/unknown constructor owner stays fail-closed rather than being masked out.
  for (uint8_t unknown : {uint8_t(0x08), uint8_t(0x80), uint8_t(0xff)}) {
    WisBlockSharedPowerPolicy held(unknown);
    assert(held.configure(WisBlockPeripheralMode::GpsOnly));
    held.setDiscoveryActive(false);
    expectState(held, true, false, false, WisBlockPeripheralMode::GpsOnly,
                static_cast<uint8_t>(unknown | EXPECTED_COMPILE_HOLDS));
  }
}

int main() {
  bootAndDiscovery();
  everyOwnershipCombination();
  rejectedConfigurationRetainsOwners();
}
