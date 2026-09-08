#include <gtest/gtest.h>

#include <cstdio>
#include <cstring>
#include <string>

#include "../../examples/companion_radio/NodePrefs.h"

class ReplayStream : public Stream {
  const char* _text;
  int _pos = 0;
  int _len;

public:
  explicit ReplayStream(const char* text) : _text(text), _len(strlen(text)) { }

  int available() override { return _len - _pos; }
  int read() override { return _pos < _len ? _text[_pos++] : -1; }
  int peek() override { return _pos < _len ? _text[_pos] : -1; }
};

class CaptureStream : public Stream {
  std::string _text;

  size_t emit(long long value) {
    char text[24];
    int length = snprintf(text, sizeof(text), "%lld", value);
    return write(reinterpret_cast<const uint8_t*>(text), length);
  }

public:
  size_t write(uint8_t value) override {
    _text.push_back(static_cast<char>(value));
    return 1;
  }

  size_t write(const uint8_t* buffer, size_t size) override {
    _text.append(reinterpret_cast<const char*>(buffer), size);
    return size;
  }

  size_t print(unsigned char value, int = DEC) override { return emit(value); }
  size_t print(int value, int = DEC) override { return emit(value); }
  size_t print(unsigned int value, int = DEC) override { return emit(value); }
  size_t print(long value, int = DEC) override { return emit(value); }
  size_t print(unsigned long value, int = DEC) override { return emit(value); }
  size_t print(long long value, int = DEC) override { return emit(value); }
  size_t print(unsigned long long value, int = DEC) override { return emit(value); }

  const std::string& text() const { return _text; }
};

TEST(CompanionNodePrefs, DevicePowerSavingIsIndependentFromRxps) {
  CompanionNodePrefs prefs = {};
  prefs.rx_powersaving_enabled = 1;
  prefs.powersaving_enabled = 0;

  EXPECT_EQ(1, prefs.rx_powersaving_enabled);
  EXPECT_EQ(0, prefs.powersaving_enabled);

  prefs.powersaving_enabled = 1;
  prefs.rx_powersaving_enabled = 0;

  EXPECT_EQ(0, prefs.rx_powersaving_enabled);
  EXPECT_EQ(1, prefs.powersaving_enabled);
}

TEST(CompanionNodePrefs, WiFiStateIsIndependentFromPowerSaving) {
  CompanionNodePrefs prefs = {};
  prefs.wifi_enabled = 1;
  prefs.powersaving_enabled = 0;

  EXPECT_EQ(1, prefs.wifi_enabled);
  EXPECT_EQ(0, prefs.powersaving_enabled);

  prefs.wifi_enabled = 0;
  prefs.powersaving_enabled = 1;

  EXPECT_EQ(0, prefs.wifi_enabled);
  EXPECT_EQ(1, prefs.powersaving_enabled);
}

TEST(CompanionNodePrefs, UsbLoggingStateIsIndependentFromTransports) {
  CompanionNodePrefs prefs = {};
  prefs.usb_logging_enabled = 1;
  prefs.wifi_enabled = 0;
  prefs.powersaving_enabled = 1;

  EXPECT_EQ(1, prefs.usb_logging_enabled);
  EXPECT_EQ(0, prefs.wifi_enabled);
  EXPECT_EQ(1, prefs.powersaving_enabled);

  prefs.usb_logging_enabled = 0;
  EXPECT_EQ(0, prefs.usb_logging_enabled);
  EXPECT_EQ(0, prefs.wifi_enabled);
  EXPECT_EQ(1, prefs.powersaving_enabled);
}

TEST(CompanionNodePrefs, CadControlsAreIndependentAndDefaultable) {
  CompanionNodePrefs prefs = {};
  prefs.cad_enabled = 1;
  prefs.cad_scan_timeout_ms = 350;
  prefs.cad_retry_delay_ms = 75;
  prefs.cad_max_duration_ms = 2500;

  EXPECT_EQ(1, prefs.cad_enabled);
  EXPECT_EQ(350, prefs.cad_scan_timeout_ms);
  EXPECT_EQ(75, prefs.cad_retry_delay_ms);
  EXPECT_EQ(2500, prefs.cad_max_duration_ms);

  // Zero means use the existing SF/BW-derived or Dispatcher adaptive timing.
  prefs.cad_scan_timeout_ms = 0;
  prefs.cad_retry_delay_ms = 0;
  prefs.cad_max_duration_ms = 0;
  EXPECT_EQ(0, prefs.cad_scan_timeout_ms);
  EXPECT_EQ(0, prefs.cad_retry_delay_ms);
  EXPECT_EQ(0, prefs.cad_max_duration_ms);
  EXPECT_EQ(1, prefs.cad_enabled);
}

TEST(CompanionNodePrefs, BluetoothNameOverrideIsIndependentFromNodeName) {
  CompanionNodePrefs prefs = {};
  strcpy(prefs.node_name, "RidgeNode");
  strcpy(prefs.bluetooth_name, "Workshop Companion");

  char effective[64];
  mesh::companion::formatBluetoothName(
      effective, sizeof(effective), prefs.bluetooth_name, "MeshCore-",
      prefs.node_name);
  EXPECT_STREQ("Workshop Companion", effective);

  strcpy(prefs.bluetooth_name, "default");
  mesh::companion::formatBluetoothName(
      effective, sizeof(effective), prefs.bluetooth_name, "MeshCore-",
      prefs.node_name);
  EXPECT_STREQ("default", effective);

  prefs.bluetooth_name[0] = 0;
  mesh::companion::formatBluetoothName(
      effective, sizeof(effective), prefs.bluetooth_name, "MeshCore-",
      prefs.node_name);
  EXPECT_STREQ("MeshCore-RidgeNode", effective);
}

TEST(CompanionNodePrefs, BluetoothNameRequiresBoundedValidUtf8) {
  EXPECT_TRUE(mesh::companion::isValidBluetoothName("Field Unit 4"));
  EXPECT_TRUE(mesh::companion::isValidBluetoothName(
      "Field Unit \xF0\x9F\x93\xA1"));
  EXPECT_FALSE(mesh::companion::isValidBluetoothName(""));
  EXPECT_FALSE(mesh::companion::isValidBluetoothName("   "));
  EXPECT_FALSE(mesh::companion::isValidBluetoothName("bad\nname"));

  char too_long[mesh::companion::BLUETOOTH_NAME_SIZE + 1];
  memset(too_long, 'A', sizeof(too_long));
  too_long[sizeof(too_long) - 1] = 0;
  EXPECT_FALSE(mesh::companion::isValidBluetoothName(too_long));

  const char malformed[] = {'A', static_cast<char>(0x80), 0};
  EXPECT_FALSE(mesh::companion::isValidBluetoothName(malformed));
}

TEST(CompanionNodePrefs, BluetoothMacDefaultsToFactoryIdentity) {
  CompanionNodePrefs prefs = {};
  EXPECT_EQ(mesh::companion::BLUETOOTH_MAC_DEFAULT,
            prefs.bluetooth_mac_mode);
  EXPECT_FALSE(mesh::companion::hasCustomBluetoothMac(
      prefs.bluetooth_mac));
  EXPECT_EQ(mesh::companion::BLUETOOTH_PEER_ADDRESS_NONE,
            prefs.bluetooth_stealth_peer_type);
  EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_OFF,
            prefs.bluetooth_stealth_mode);
}

TEST(CompanionNodePrefs, BluetoothMacParsesAndFormatsRandomStaticAddress) {
  uint8_t address[mesh::companion::BLUETOOTH_MAC_BYTES] = {};
  ASSERT_TRUE(mesh::companion::parseBluetoothMac(
      "C2:11:22:33:44:55", address));
  EXPECT_EQ(0xC2, address[0]);
  EXPECT_EQ(0x55, address[5]);

  char formatted[mesh::companion::BLUETOOTH_MAC_TEXT_SIZE];
  ASSERT_TRUE(mesh::companion::formatBluetoothMac(
      address, formatted, sizeof(formatted)));
  EXPECT_STREQ("C2:11:22:33:44:55", formatted);

  ASSERT_TRUE(mesh::companion::parseBluetoothMac(
      "d6-aa-bb-cc-dd-ee", address));
  ASSERT_TRUE(mesh::companion::formatBluetoothMac(
      address, formatted, sizeof(formatted)));
  EXPECT_STREQ("D6:AA:BB:CC:DD:EE", formatted);
}

TEST(CompanionNodePrefs, BluetoothMacRejectsInvalidOrMalformedAddress) {
  uint8_t address[mesh::companion::BLUETOOTH_MAC_BYTES];
  memset(address, 0xA5, sizeof(address));

  EXPECT_FALSE(mesh::companion::parseBluetoothMac(
      "02:11:22:33:44:55", address));
  EXPECT_FALSE(mesh::companion::parseBluetoothMac(
      "C0:00:00:00:00:00", address));
  EXPECT_FALSE(mesh::companion::parseBluetoothMac(
      "FF:FF:FF:FF:FF:FF", address));
  EXPECT_FALSE(mesh::companion::parseBluetoothMac(
      "C2:11-22:33:44:55", address));
  EXPECT_FALSE(mesh::companion::parseBluetoothMac(
      "C2:11:22:33:44", address));

  for (size_t i = 0; i < sizeof(address); i++) {
    EXPECT_EQ(0xA5, address[i]);
  }
}

TEST(CompanionNodePrefs, BluetoothMacRandomBytesAreNormalized) {
  uint8_t all_zero[mesh::companion::BLUETOOTH_MAC_BYTES] = {};
  mesh::companion::makeRandomStaticBluetoothMac(all_zero);
  EXPECT_TRUE(mesh::companion::isValidBluetoothMac(all_zero));
  EXPECT_EQ(0xC0, all_zero[0]);

  uint8_t all_one[mesh::companion::BLUETOOTH_MAC_BYTES];
  memset(all_one, 0xFF, sizeof(all_one));
  mesh::companion::makeRandomStaticBluetoothMac(all_one);
  EXPECT_TRUE(mesh::companion::isValidBluetoothMac(all_one));
  EXPECT_EQ(0xFE, all_one[5]);
}

TEST(CompanionNodePrefs,
     BluetoothMacRandomAfterConnectCannotReuseTheOldAddress) {
  uint8_t address[mesh::companion::BLUETOOTH_MAC_BYTES] = {
      0xC0, 0x00, 0x00, 0x00, 0x00, 0x01};
  uint8_t previous[mesh::companion::BLUETOOTH_MAC_BYTES];
  memcpy(previous, address, sizeof(previous));

  mesh::companion::makeRandomStaticBluetoothMacDifferentFrom(
      address, previous);
  EXPECT_TRUE(mesh::companion::isValidBluetoothMac(address));
  EXPECT_NE(0, memcmp(address, previous, sizeof(address)));

  memset(address, 0xFF, sizeof(address));
  address[5] = 0xFE;
  memcpy(previous, address, sizeof(previous));
  mesh::companion::makeRandomStaticBluetoothMacDifferentFrom(
      address, previous);
  EXPECT_TRUE(mesh::companion::isValidBluetoothMac(address));
  EXPECT_NE(0, memcmp(address, previous, sizeof(address)));
}

TEST(CompanionNodePrefs, BluetoothMacModesDescribeSavedAndPerBootUse) {
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_DEFAULT));
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_CUSTOM));
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_RANDOM_SAVED));
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_RANDOM_EVERY_BOOT));
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT));
  EXPECT_TRUE(mesh::companion::isValidBluetoothMacMode(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED));
  EXPECT_FALSE(mesh::companion::isValidBluetoothMacMode(6));
  EXPECT_FALSE(mesh::companion::isValidBluetoothMacMode(7));
  EXPECT_FALSE(mesh::companion::isValidBluetoothMacMode(8));
  EXPECT_TRUE(mesh::companion::bluetoothMacModeUsesSavedAddress(
      mesh::companion::BLUETOOTH_MAC_CUSTOM));
  EXPECT_TRUE(mesh::companion::bluetoothMacModeUsesSavedAddress(
      mesh::companion::BLUETOOTH_MAC_RANDOM_SAVED));
  EXPECT_TRUE(mesh::companion::bluetoothMacModeUsesSavedAddress(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT));
  EXPECT_FALSE(mesh::companion::bluetoothMacModeUsesSavedAddress(
      mesh::companion::BLUETOOTH_MAC_RANDOM_EVERY_BOOT));
}

TEST(CompanionNodePrefs,
     BluetoothMacRandomAfterConnectRotatesOnlyWhenArmedOrInvalid) {
  const uint8_t valid[mesh::companion::BLUETOOTH_MAC_BYTES] = {
      0xC2, 0x11, 0x22, 0x33, 0x44, 0x55};
  const uint8_t invalid[mesh::companion::BLUETOOTH_MAC_BYTES] = {};

  EXPECT_TRUE(mesh::companion::bluetoothMacModeIsRandomAfterConnect(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT));
  EXPECT_TRUE(mesh::companion::bluetoothMacModeIsRandomAfterConnect(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED));
  EXPECT_FALSE(mesh::companion::bluetoothMacModeIsRandomAfterConnect(
      mesh::companion::BLUETOOTH_MAC_RANDOM_EVERY_BOOT));

  EXPECT_FALSE(mesh::companion::bluetoothMacShouldRotateAtBoot(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT, valid));
  EXPECT_TRUE(mesh::companion::bluetoothMacShouldRotateAtBoot(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED, valid));
  EXPECT_TRUE(mesh::companion::bluetoothMacShouldRotateAtBoot(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT, invalid));
  EXPECT_FALSE(mesh::companion::bluetoothMacShouldRotateAtBoot(
      mesh::companion::BLUETOOTH_MAC_RANDOM_SAVED, invalid));
}

TEST(CompanionNodePrefs, BluetoothStealthTracksPairingIndependently) {
  EXPECT_TRUE(mesh::companion::bluetoothStealthEnabled(
      mesh::companion::BLUETOOTH_STEALTH_PAIRING));
  EXPECT_TRUE(mesh::companion::bluetoothStealthEnabled(
      mesh::companion::BLUETOOTH_STEALTH_PAIRED));
  EXPECT_FALSE(mesh::companion::bluetoothStealthEnabled(
      mesh::companion::BLUETOOTH_STEALTH_OFF));
  EXPECT_FALSE(mesh::companion::isValidBluetoothStealthMode(3));
  EXPECT_FALSE(mesh::companion::bluetoothStealthEnabled(255));

  mesh::companion::BluetoothPeerIdentity peer;
  EXPECT_FALSE(mesh::companion::isValidBluetoothPeerIdentity(peer));
  peer.type = mesh::companion::BLUETOOTH_PEER_ADDRESS_RANDOM;
  peer.address[0] = 0xC2;
  peer.address[5] = 0x55;
  EXPECT_TRUE(mesh::companion::isValidBluetoothPeerIdentity(peer));
  peer.type = 3;
  EXPECT_FALSE(mesh::companion::isValidBluetoothPeerIdentity(peer));
}

TEST(CompanionNodePrefs, StealthFlagPreservesEveryMacPolicyAndAddress) {
  const uint8_t address[] = {0xC2, 0x11, 0x22, 0x33, 0x44, 0x55};
  for (uint8_t mode = mesh::companion::BLUETOOTH_MAC_DEFAULT;
       mode <= mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED;
       mode++) {
    CompanionNodePrefs prefs;
    prefs.bluetooth_mac_mode = mode;
    memcpy(prefs.bluetooth_mac, address, sizeof(address));
    EXPECT_TRUE(setCompanionBluetoothStealth(prefs, true));
    EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_PAIRING,
              prefs.bluetooth_stealth_mode);
    EXPECT_EQ(mode, prefs.bluetooth_mac_mode);
    EXPECT_EQ(0, memcmp(address, prefs.bluetooth_mac, sizeof(address)));

    prefs.bluetooth_stealth_mode = mesh::companion::BLUETOOTH_STEALTH_PAIRED;
    prefs.bluetooth_stealth_peer_type = mesh::companion::BLUETOOTH_PEER_ADDRESS_PUBLIC;
    memcpy(prefs.bluetooth_stealth_peer, address, sizeof(address));
    EXPECT_FALSE(setCompanionBluetoothStealth(prefs, true));
    EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_PAIRED,
              prefs.bluetooth_stealth_mode);
    EXPECT_EQ(0, memcmp(address, prefs.bluetooth_stealth_peer, sizeof(address)));

    EXPECT_TRUE(setCompanionBluetoothStealth(prefs, false));
    EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_OFF, prefs.bluetooth_stealth_mode);
    EXPECT_EQ(mode, prefs.bluetooth_mac_mode);
    EXPECT_EQ(0, memcmp(address, prefs.bluetooth_mac, sizeof(address)));
    EXPECT_EQ(mesh::companion::BLUETOOTH_PEER_ADDRESS_NONE,
              prefs.bluetooth_stealth_peer_type);
    const uint8_t empty[mesh::companion::BLUETOOTH_MAC_BYTES] = {};
    EXPECT_EQ(0, memcmp(empty, prefs.bluetooth_stealth_peer, sizeof(empty)));
    EXPECT_FALSE(setCompanionBluetoothStealth(prefs, false));
  }
}

TEST(CompanionNodePrefs, AddressChangeReopensPairingWithoutDisablingStealth) {
  CompanionNodePrefs prefs;
  prefs.bluetooth_mac_mode = mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED;
  prefs.bluetooth_stealth_mode = mesh::companion::BLUETOOTH_STEALTH_PAIRED;
  prefs.bluetooth_stealth_peer_type = mesh::companion::BLUETOOTH_PEER_ADDRESS_PUBLIC;
  memset(prefs.bluetooth_stealth_peer, 0x12, sizeof(prefs.bluetooth_stealth_peer));
  clearCompanionBluetoothStealthPeer(prefs);
  EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_PAIRING,
            prefs.bluetooth_stealth_mode);
  EXPECT_EQ(mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED,
            prefs.bluetooth_mac_mode);
  EXPECT_EQ(mesh::companion::BLUETOOTH_PEER_ADDRESS_NONE,
            prefs.bluetooth_stealth_peer_type);

  prefs.bluetooth_stealth_mode = mesh::companion::BLUETOOTH_STEALTH_OFF;
  clearCompanionBluetoothStealthPeer(prefs);
  EXPECT_EQ(mesh::companion::BLUETOOTH_STEALTH_OFF, prefs.bluetooth_stealth_mode);
}

TEST(CompanionNodePrefs, ArmingRotationDoesNotChangeSessionPolicy) {
  EXPECT_TRUE(mesh::companion::bluetoothMacPoliciesMatch(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT,
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED));
  EXPECT_TRUE(mesh::companion::bluetoothMacPoliciesMatch(
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT_ARMED,
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT));
  EXPECT_FALSE(mesh::companion::bluetoothMacPoliciesMatch(
      mesh::companion::BLUETOOTH_MAC_RANDOM_EVERY_BOOT,
      mesh::companion::BLUETOOTH_MAC_RANDOM_AFTER_CONNECT));
}

TEST(CompanionNodePrefs, MigratesRegressedPowerSavingDefaultOnce) {
  CompanionNodePrefs prefs = {};
  prefs.powersaving_enabled = 0;
  prefs.powersaving_policy_version = 0;

  EXPECT_TRUE(migrateCompanionPowerSavingDefault(prefs));
  EXPECT_EQ(1, prefs.powersaving_enabled);
  EXPECT_EQ(COMPANION_POWERSAVING_POLICY_VERSION,
            prefs.powersaving_policy_version);

  // Once migrated, an explicit user choice to turn power saving off remains
  // untouched on later boots.
  prefs.powersaving_enabled = 0;
  EXPECT_FALSE(migrateCompanionPowerSavingDefault(prefs));
  EXPECT_EQ(0, prefs.powersaving_enabled);
}

#if 0
// Re-enable test once we can SET fem_ values in companion
TEST(CompanionNodePrefs, RxGainSettingsRoundTripIndependently) {
  NodePrefs saved;
  saved.rx_boosted_gain = 0;
  saved.radio_fem_rxgain = 1;
  saved.radio_fem_txgain = 0;

  CaptureStream output;
  ASSERT_TRUE(saved.saveSerial(output));
  EXPECT_NE(std::string::npos, output.text().find("rxgain:0"));
  EXPECT_NE(std::string::npos, output.text().find("fem_rxgain:1"));
  EXPECT_NE(std::string::npos, output.text().find("fem_txgain:0"));

  ReplayStream input("{radio:{rxgain:1,fem_rxgain:0,fem_txgain:1}}");
  NodePrefs loaded;
  loaded.rx_boosted_gain = 0;
  loaded.radio_fem_rxgain = 1;
  loaded.radio_fem_txgain = 0;

  ASSERT_TRUE(loaded.loadSerial(input));
  EXPECT_EQ(1, loaded.rx_boosted_gain);
  EXPECT_EQ(0, loaded.radio_fem_rxgain);
  EXPECT_EQ(1, loaded.radio_fem_txgain);
}
#endif

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
