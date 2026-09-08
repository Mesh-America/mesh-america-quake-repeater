#include <gtest/gtest.h>

#include <helpers/RadioLivenessTracker.h>
#include <helpers/radiolib/LR2021Band.h>
#include <helpers/radiolib/RxBoostedGainDefaults.h>
#include <Dispatcher.h>
#include <helpers/StaticPoolPacketManager.h>

using mesh::RadioLivenessTracker;
using mesh::RadioRecoveryAction;

TEST(RxBoostedGainDefaults, UsesTargetCompileTimeSetting) {
  using mesh::radio::selectRxBoostedGainDefault;

  EXPECT_EQ(selectRxBoostedGainDefault(true, 0, false, 0), 0);
  EXPECT_EQ(selectRxBoostedGainDefault(true, 1, false, 0), 1);
  EXPECT_EQ(selectRxBoostedGainDefault(false, 0, true, 0), 0);
  EXPECT_EQ(selectRxBoostedGainDefault(false, 0, true, 1), 1);
  EXPECT_EQ(selectRxBoostedGainDefault(false, 0, false, 0), 1);
}

TEST(RxBoostedGainDefaults, Sx126xSettingTakesPrecedence) {
  using mesh::radio::selectRxBoostedGainDefault;

  EXPECT_EQ(selectRxBoostedGainDefault(true, 0, true, 1), 0);
  EXPECT_EQ(selectRxBoostedGainDefault(true, 1, true, 0), 1);
}

TEST(RadioLivenessTracker, StagesSoftThenHardRecovery) {
  RadioLivenessTracker tracker;
  tracker.begin(1000);
  EXPECT_EQ(tracker.poll(1999, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(2000, 1000, 5000), RadioRecoveryAction::SOFT);
  EXPECT_EQ(tracker.poll(3000, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(6000, 1000, 5000), RadioRecoveryAction::HARD);
  EXPECT_EQ(tracker.poll(6999, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(35999, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(36000, 1000, 5000), RadioRecoveryAction::HARD);
  tracker.noteHardRecoveryResult(36000, true);
  EXPECT_EQ(tracker.poll(36999, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(37000, 1000, 5000), RadioRecoveryAction::SOFT);
}

TEST(RadioLivenessTracker, HardwareActivityCancelsEscalation) {
  RadioLivenessTracker tracker;
  tracker.begin(0);
  EXPECT_EQ(tracker.poll(1000, 1000, 5000), RadioRecoveryAction::SOFT);
  tracker.noteActivity(1200);
  EXPECT_EQ(tracker.stage(), 0);
  EXPECT_EQ(tracker.poll(2199, 1000, 5000), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(2200, 1000, 5000), RadioRecoveryAction::SOFT);
}

TEST(RadioLivenessTracker, ElapsedTimeIsRolloverSafe) {
  RadioLivenessTracker tracker;
  tracker.begin(0xFFFFFF00UL);
  EXPECT_EQ(tracker.poll(0x000000FFUL, 512, 4096), RadioRecoveryAction::NONE);
  EXPECT_EQ(tracker.poll(0x00000100UL, 512, 4096), RadioRecoveryAction::SOFT);
}

TEST(LR2021Band, SelectsTheCorrectFrontEnd) {
  EXPECT_FALSE(mesh::lr2021::isHighBand(1090.0f));
  EXPECT_FALSE(mesh::lr2021::isHighBand(1500.0f));
  EXPECT_TRUE(mesh::lr2021::isHighBand(1900.0f));
  EXPECT_TRUE(mesh::lr2021::isHighBand(2400.0f));
}

namespace {
class AdvancingClock : public mesh::MillisecondClock {
public:
  unsigned long now = 1;
  unsigned long getMillis() override { return now++; }
};

class BurstRadio : public mesh::Radio {
public:
  bool receiving = true;
  bool cad_busy = false;
  bool broken_rx = false;
  int completed = 0;
  int recoveries = 0;
  int recvRaw(uint8_t*, int) override {
    if (!broken_rx) receiving = true;
    return 0;
  }
  uint32_t getEstAirtimeFor(int) override { return 1000; }
  float packetScore(float, int) override { return 1; }
  bool startSendRaw(const uint8_t*, int) override {
    receiving = false;
    return true;
  }
  bool isSendComplete() override { ++completed; return true; }
  void onSendFinished() override { receiving = false; }
  bool isInRecvMode() const override { return receiving; }
  bool isReceiving() override {
    // Active CAD may leave the radio outside RX until the next recvRaw().
    if (cad_busy) receiving = false;
    return cad_busy;
  }
  bool recoverRadio(bool) override {
    ++recoveries;
    receiving = !broken_rx;
    return !broken_rx;
  }
};

class WatchdogDispatcher : public mesh::Dispatcher {
public:
  WatchdogDispatcher(BurstRadio& radio, AdvancingClock& clock,
                     StaticPoolPacketManager& packets)
      : Dispatcher(radio, clock, packets) {}
  mesh::DispatcherAction onRecvPacket(mesh::Packet*) override { return ACTION_RELEASE; }
  uint16_t errors() const { return _err_flags; }
};
}

TEST(DispatcherRadioWatchdog, SuccessfulTxBurstDoesNotTriggerStuckRxRecovery) {
  AdvancingClock clock;
  BurstRadio radio;
  StaticPoolPacketManager packets(16);
  WatchdogDispatcher dispatcher(radio, clock, packets);
  dispatcher.begin();
  for (int i = 0; i < 12; ++i) {
    auto* packet = packets.allocNew();
    ASSERT_NE(packet, nullptr);
    packet->header = ROUTE_TYPE_DIRECT | (PAYLOAD_TYPE_TXT_MSG << 2);
    packet->path_len = 0;
    packet->payload_len = 1;
    packet->payload[0] = 0;
    ASSERT_TRUE(dispatcher.sendPacket(packet, 0));
  }
  dispatcher.loop();
  // RX happens inside each loop between completed TX and the next TX. The
  // watchdog at the top of the loop sees only TX, for longer than 8 seconds.
  for (int i = 0; i < 10; ++i) {
    clock.now += 1000;
    if (i == 9) radio.cad_busy = true;
    dispatcher.loop();
  }
  ASSERT_EQ(radio.completed, 10);
  clock.now += 100;
  dispatcher.loop();
  EXPECT_EQ(radio.recoveries, 0);
  EXPECT_EQ(dispatcher.errors() & ERR_EVENT_STARTRX_TIMEOUT, 0);

  // A subsequent genuine RX failure still gets its own recovery deadline.
  radio.broken_rx = true;
  clock.now += 8100;
  dispatcher.loop();
  EXPECT_EQ(radio.recoveries, 1);
  EXPECT_NE(dispatcher.errors() & ERR_EVENT_STARTRX_TIMEOUT, 0);
}

TEST(DispatcherRadioWatchdog, StuckReceiverStillRecoversWithoutTransmitActivity) {
  AdvancingClock clock;
  BurstRadio radio;
  StaticPoolPacketManager packets(2);
  WatchdogDispatcher dispatcher(radio, clock, packets);
  dispatcher.begin();
  radio.broken_rx = true;
  radio.receiving = false;
  dispatcher.loop();
  clock.now += 8100;
  dispatcher.loop();
  EXPECT_EQ(radio.recoveries, 1);
  EXPECT_NE(dispatcher.errors() & ERR_EVENT_STARTRX_TIMEOUT, 0);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
