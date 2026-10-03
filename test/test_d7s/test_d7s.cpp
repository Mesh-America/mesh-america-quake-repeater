#include <gtest/gtest.h>
#include <helpers/sensors/D7S.h>
#include <map>
#include <vector>

class FakeBus : public d7s::Transport {
public:
  std::map<uint16_t, uint8_t> registers;
  std::vector<uint16_t> reads;
  int failAt = -1;
  bool writeFails = false;
  int writes = 0;
  bool clearOnFailedEventRead = false;  // Models a device that cleared EVENT before the NACK/timeout.
  bool read(uint16_t reg, uint8_t* data, size_t size) override {
    reads.push_back(reg);
    if (reg == failAt) {
      if (reg == 0x1002 && clearOnFailedEventRead) registers[reg] = 0;
      return false;
    }
    for (size_t i = 0; i < size; ++i) data[i] = registers[reg + i];
    if (reg == 0x1002) registers[reg] = 0;
    return true;
  }
  bool write(uint16_t reg, uint8_t value) override {
    ++writes;
    if (writeFails) return false;
    registers[reg] = value;
    return true;
  }
};

TEST(D7S, StandbyIsReadyWithoutWritingOrRecalibrating) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  EXPECT_TRUE(sensor.service(0));
  EXPECT_TRUE(sensor.snapshot().valid);
  EXPECT_EQ(sensor.snapshot().state, d7s::State::Standby);
  EXPECT_EQ(bus.writes, 0);
}

TEST(D7S, BothInterruptsTriggerServiceAndBothAlertBitsSurviveReadToClear) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  bus.registers[0x1002] = 3;
  sensor.notify(d7s::Int1);
  sensor.notify(d7s::Int2);
  EXPECT_FALSE(sensor.service(1));  // Notification floor: not before 20 ms.
  EXPECT_TRUE(sensor.service(20));
  EXPECT_EQ(sensor.snapshot().interrupts, 3);
  EXPECT_EQ(bus.registers[0x1002], 0);
  EXPECT_TRUE(sensor.service(270));
  EXPECT_EQ(sensor.takeEvents(), 3);
  EXPECT_EQ(sensor.takeEvents(), 0);
  EXPECT_EQ(sensor.takeInterrupts(), 3);
  EXPECT_EQ(sensor.takeInterrupts(), 0);
}

TEST(D7S, LiveReadUsesBigEndianAndOnlyPublishesCompleteData) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1000] = 1;
  bus.registers[0x2000] = 0x12;
  bus.registers[0x2001] = 0x34;
  bus.registers[0x2002] = 0xab;
  bus.registers[0x2003] = 0xcd;
  ASSERT_TRUE(sensor.service(0));
  EXPECT_TRUE(sensor.snapshot().liveValid);
  EXPECT_EQ(sensor.snapshot().live.siRaw, 0x1234);
  EXPECT_EQ(sensor.snapshot().live.pgaRaw, 0xabcd);
  bus.failAt = 0x2000;
  bus.registers[0x1002] = 2;
  EXPECT_FALSE(sensor.service(250));
  EXPECT_FALSE(sensor.snapshot().liveValid);
  EXPECT_FALSE(sensor.snapshot().valid);
  EXPECT_EQ(sensor.takeEvents(), 2);
}

TEST(D7S, Int2DuringSelfTestIsNotReportedAsEarthquake) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1000] = 4;
  bus.registers[0x1002] = 4;
  sensor.notify(d7s::Int2);
  ASSERT_TRUE(sensor.service(0));
  EXPECT_EQ(sensor.snapshot().state, d7s::State::SelfTest);
  EXPECT_FALSE(sensor.snapshot().liveValid);
  EXPECT_EQ(sensor.takeEvents(), 4);
  EXPECT_EQ(bus.reads.size(), 2u);
}

TEST(D7S, FailedEventReadExplicitlyMarksPossibleLoss) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.failAt = 0x1002;
  sensor.notify(d7s::Int1);
  EXPECT_FALSE(sensor.service(0));
  EXPECT_TRUE(sensor.snapshot().eventReadUncertain);
  EXPECT_EQ(sensor.snapshot().failures, 1u);
  EXPECT_EQ(sensor.takeInterrupts(), d7s::Int1);
}

TEST(D7S, MissingSensorBacksOffEvenDuringInterruptStormAndRecovers) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(0));
  sensor.notify(3);
  EXPECT_FALSE(sensor.service(1));
  EXPECT_EQ(bus.reads.size(), 1u);
  bus.failAt = -1;
  EXPECT_FALSE(sensor.service(4999));
  EXPECT_EQ(bus.reads.size(), 1u);
  EXPECT_TRUE(sensor.service(5000));
  EXPECT_EQ(sensor.takeInterrupts(), 3);
}

TEST(D7S, PollTimerWorksAcrossMillisWrap) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0xffffff9cu));
  EXPECT_FALSE(sensor.service(0));
  EXPECT_TRUE(sensor.service(150));
}

TEST(D7S, StoredBoundsAndRankedAddressAndFailurePreserveOutput) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  d7s::Reading reading{9, 10};
  EXPECT_FALSE(sensor.readStored(5, false, reading));
  EXPECT_TRUE(bus.reads.empty());
  bus.registers[0x3908] = 1;
  ASSERT_TRUE(sensor.readStored(4, true, reading));
  EXPECT_EQ(reading.siRaw, 256);
  EXPECT_EQ(bus.reads.back(), 0x3908);
  bus.failAt = 0x3008;
  EXPECT_FALSE(sensor.readStored(0, false, reading));
  EXPECT_EQ(reading.siRaw, 256);
}

TEST(D7S, CommandsRequireCurrentStandbyAndPropagateWriteFailure) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1000] = 1;
  EXPECT_FALSE(sensor.command(d7s::Command::Install));
  EXPECT_EQ(bus.writes, 0);
  bus.registers[0x1000] = 0;
  EXPECT_TRUE(sensor.command(d7s::Command::SelfTest));
  EXPECT_EQ(bus.registers[0x1003], 4);
  bus.writeFails = true;
  EXPECT_FALSE(sensor.command(d7s::Command::Install));
  EXPECT_FALSE(sensor.command(static_cast<d7s::Command>(5)));
}

TEST(D7S, InvalidStateIsRejectedAndPreviousLiveDataBecomesInvalidAtStandby) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1000] = 7;
  EXPECT_FALSE(sensor.service(0));
  bus.registers[0x1000] = 1;
  EXPECT_TRUE(sensor.service(5000));
  EXPECT_TRUE(sensor.snapshot().liveValid);
  bus.registers[0x1000] = 0;
  EXPECT_TRUE(sensor.service(5250));
  EXPECT_FALSE(sensor.snapshot().liveValid);
}

TEST(D7S, StoredHistoryIsDistinctFromLiveAndRefreshesAfterProcessing) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x3009] = 12;
  ASSERT_TRUE(sensor.service(0));
  EXPECT_TRUE(sensor.snapshot().storedValid);
  EXPECT_FALSE(sensor.snapshot().liveValid);
  EXPECT_EQ(sensor.snapshot().stored.siRaw, 12);
  bus.registers[0x1000] = 1;
  ASSERT_TRUE(sensor.service(250));
  EXPECT_FALSE(sensor.snapshot().storedValid);
  bus.registers[0x1000] = 0;
  bus.registers[0x3009] = 34;
  bus.failAt = 0x3008;
  EXPECT_FALSE(sensor.service(500));
  EXPECT_FALSE(sensor.snapshot().storedValid);
  bus.failAt = -1;
  ASSERT_TRUE(sensor.service(5500));
  EXPECT_TRUE(sensor.snapshot().storedValid);
  EXPECT_EQ(sensor.snapshot().stored.siRaw, 34);
}

TEST(D7S, LostEventFlagsAreVisibleInTheReportAndStayUntilAcknowledged) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  EXPECT_EQ(sensor.snapshot().eventReport(), 0);
  bus.registers[0x1002] = 1;  // Significant shaking, cleared by the device during the failed read.
  bus.failAt = 0x1002;
  bus.clearOnFailedEventRead = true;
  EXPECT_FALSE(sensor.service(250));
  EXPECT_EQ(bus.registers[0x1002], 0);
  EXPECT_EQ(sensor.snapshot().events, 0);  // The flag itself is gone...
  EXPECT_EQ(sensor.snapshot().eventReport(), d7s::ReadUncertain);  // ...but not silently.
  bus.failAt = -1;
  ASSERT_TRUE(sensor.service(5250));  // A later good read does not erase the doubt.
  EXPECT_EQ(sensor.snapshot().eventReport(), d7s::ReadUncertain);
  EXPECT_EQ(sensor.takeEvents(), d7s::ReadUncertain);
  EXPECT_EQ(sensor.snapshot().eventReport(), 0);
}

TEST(D7S, UncertaintyMarkerCombinesWithObservedFlagsAndOnlyUsesTheReservedBit) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1002] = 0x0f;
  ASSERT_TRUE(sensor.service(0));
  bus.failAt = 0x1002;
  EXPECT_FALSE(sensor.service(250));
  EXPECT_EQ(sensor.snapshot().eventReport(), 0x8f);
  EXPECT_EQ(d7s::ReadUncertain & 0x0f, 0);
}

TEST(D7S, FailedStateReadCannotHaveClearedEventsSoNoUncertainty) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(0));
  EXPECT_FALSE(sensor.snapshot().eventReadUncertain);
}

TEST(D7S, HealthyInterruptStormIsRateLimitedToTheNotificationFloor) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  bus.reads.clear();
  int serviced = 0;
  for (uint32_t t = 1; t <= 1000; ++t) {  // A notification every millisecond for one second.
    sensor.notify(d7s::Int1 | d7s::Int2);
    if (sensor.service(t)) ++serviced;
  }
  EXPECT_LE(serviced, 50);
  EXPECT_GE(serviced, 49);  // Still responsive: not starved by the limiter.
  EXPECT_LE(bus.reads.size(), size_t(serviced) * 3);
}

TEST(D7S, NotificationNeverShortensTheFailureRetry) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(0));
  for (uint32_t t = 1; t < 5000; t += 7) {
    sensor.notify(d7s::Int1);
    EXPECT_FALSE(sensor.service(t));
  }
  EXPECT_EQ(bus.reads.size(), 1u);
}

TEST(D7S, NotificationFloorSurvivesMillisWrap) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0xfffffff6u));
  sensor.notify(d7s::Int2);
  EXPECT_FALSE(sensor.service(0));  // 10 ms elapsed across the wrap.
  EXPECT_TRUE(sensor.service(10));  // 20 ms.
}

TEST(D7S, StoredRecordIsRefetchedWhenAShakingFlagArrivesWithoutAnObservedProcessingState) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x3009] = 10;
  ASSERT_TRUE(sensor.service(0));
  EXPECT_EQ(sensor.snapshot().stored.siRaw, 10);
  bus.registers[0x3009] = 255;  // A record stored while the sensor was never seen non-standby.
  bus.registers[0x1002] = 1;
  ASSERT_TRUE(sensor.service(250));
  EXPECT_EQ(sensor.snapshot().stored.siRaw, 255);
  EXPECT_TRUE(sensor.snapshot().storedValid);
}

TEST(D7S, StoredRecordIsRefetchedAfterAnyFailedPoll) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x3009] = 10;
  ASSERT_TRUE(sensor.service(0));
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(250));
  EXPECT_FALSE(sensor.snapshot().storedValid);
  bus.failAt = -1;
  bus.registers[0x3009] = 77;
  ASSERT_TRUE(sensor.service(5250));
  EXPECT_EQ(sensor.snapshot().stored.siRaw, 77);
}

TEST(D7S, EverValidIsSetOnlyByASuccessfulPollAndSurvivesLaterFailures) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(0));
  EXPECT_FALSE(sensor.snapshot().everValid);
  bus.failAt = -1;
  ASSERT_TRUE(sensor.service(5000));
  EXPECT_TRUE(sensor.snapshot().everValid);
  bus.failAt = 0x1000;
  EXPECT_FALSE(sensor.service(5250));
  EXPECT_TRUE(sensor.snapshot().everValid);
  EXPECT_FALSE(sensor.snapshot().valid);
}

TEST(D7S, GarbageStateNeverCountsAsAConfirmedSensor) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1000] = 0xff;  // A foreign device answering at the same address.
  EXPECT_FALSE(sensor.service(0));
  EXPECT_FALSE(sensor.snapshot().everValid);
  bus.registers[0x1000] = 5;
  EXPECT_FALSE(sensor.service(5000));
  bus.registers[0x1000] = 6;
  EXPECT_FALSE(sensor.service(10000));
  EXPECT_FALSE(sensor.snapshot().everValid);
}

TEST(D7S, FailureOfAnyReadEntersTheRetryBackoffAndRefetchesStoredDataAfterwards) {
  const int failing[] = {0x1002, 0x2000, 0x3008};
  for (int reg : failing) {
    FakeBus bus;
    d7s::Sensor sensor(bus);
    bus.registers[0x1000] = reg == 0x2000 ? 1 : 0;
    bus.failAt = reg;
    ASSERT_FALSE(sensor.service(0)) << std::hex << reg;
    const size_t reads = bus.reads.size();
    EXPECT_FALSE(sensor.service(249)) << std::hex << reg;
    EXPECT_FALSE(sensor.service(4999)) << std::hex << reg;
    EXPECT_EQ(bus.reads.size(), reads) << std::hex << reg;  // No traffic during the 5 s backoff.
    bus.failAt = -1;
    EXPECT_TRUE(sensor.service(5000)) << std::hex << reg;
  }
}

TEST(D7S, CommandsWriteTheDocumentedModeValues) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  EXPECT_TRUE(sensor.command(d7s::Command::Install));
  EXPECT_EQ(bus.registers[0x1003], 2);
  EXPECT_TRUE(sensor.command(d7s::Command::AcquireOffset));
  EXPECT_EQ(bus.registers[0x1003], 3);
  EXPECT_TRUE(sensor.command(d7s::Command::SelfTest));
  EXPECT_EQ(bus.registers[0x1003], 4);
  EXPECT_FALSE(sensor.command(static_cast<d7s::Command>(1)));
  EXPECT_EQ(bus.registers[0x1003], 4);  // Rejected values are never written.
}

TEST(D7S, ACommandInvalidatesTheSnapshotAndIsRefusedWhenTheStateReadFails) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  ASSERT_TRUE(sensor.snapshot().valid);
  EXPECT_TRUE(sensor.command(d7s::Command::SelfTest));
  EXPECT_FALSE(sensor.snapshot().valid);
  bus.failAt = 0x1000;
  const int writes = bus.writes;
  EXPECT_FALSE(sensor.command(d7s::Command::Install));
  EXPECT_EQ(bus.writes, writes);
}

TEST(D7S, NotificationsAreDrainedByAServiceCallSoTheNextPollWaitsTheFullInterval) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  sensor.notify(d7s::Int1);
  ASSERT_TRUE(sensor.service(20));
  EXPECT_FALSE(sensor.service(40));   // No new notification: back to the 250 ms poll.
  EXPECT_FALSE(sensor.service(269));
  EXPECT_TRUE(sensor.service(270));
}

TEST(D7S, EventFlagsOutsideTheDefinedBitsAreMaskedOut) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x1002] = 0xf5;
  ASSERT_TRUE(sensor.service(0));
  EXPECT_EQ(sensor.snapshot().events, 0x05);
  EXPECT_EQ(sensor.snapshot().eventReport(), 0x05);
}

TEST(D7S, StoredRecordIsRefetchedAfterEveryProcessingEpisodeNotOnlyTheFirst) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  bus.registers[0x3009] = 1;
  ASSERT_TRUE(sensor.service(0));
  for (int round = 0; round < 2; ++round) {
    bus.registers[0x1000] = 1;
    ASSERT_TRUE(sensor.service(250 + round * 1000));
    bus.registers[0x1000] = 0;
    bus.registers[0x3009] = uint8_t(20 + round);
    ASSERT_TRUE(sensor.service(500 + round * 1000));
    EXPECT_EQ(sensor.snapshot().stored.siRaw, 20 + round);
  }
}

TEST(D7S, ShakingCountCountsEachReportedEventOnceAndNeverResets) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  EXPECT_EQ(sensor.snapshot().shakingCount, 0u);
  bus.registers[0x1002] = d7s::SignificantShaking;
  ASSERT_TRUE(sensor.service(250));
  EXPECT_EQ(sensor.snapshot().shakingCount, 1u);
  ASSERT_TRUE(sensor.service(500));  // EVENT was cleared by the read: the same report is not counted twice.
  EXPECT_EQ(sensor.snapshot().shakingCount, 1u);
  bus.registers[0x1002] = d7s::SignificantShaking | d7s::Tilt;
  ASSERT_TRUE(sensor.service(750));
  EXPECT_EQ(sensor.snapshot().shakingCount, 2u);
  sensor.takeEvents();  // Acknowledging the latched flags does not forget how many were seen.
  EXPECT_EQ(sensor.snapshot().shakingCount, 2u);
}

TEST(D7S, OnlyTheSignificantShakingFlagIsCounted) {
  FakeBus bus;
  d7s::Sensor sensor(bus);
  ASSERT_TRUE(sensor.service(0));
  for (uint8_t flags : {uint8_t(d7s::Tilt), uint8_t(d7s::SelfTestError), uint8_t(d7s::BaselineError)}) {
    bus.registers[0x1002] = flags;
    ASSERT_TRUE(sensor.service(sensor.snapshot().updatedAt + 250));
  }
  EXPECT_EQ(sensor.snapshot().shakingCount, 0u);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
