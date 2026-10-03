#include <gtest/gtest.h>
#include "FakeWire.h"
#include <helpers/sensors/D7SWireTransport.h>

namespace {
class WireTransportTest : public ::testing::Test {
protected:
  FakeWire wire;
  d7s::BasicWireTransport<FakeWire> bus;
  void SetUp() override { bus.begin(&wire); }
};
}  // namespace

TEST_F(WireTransportTest, ReadSendsBigEndianRegisterWithRepeatedStartAndReturnsBytes) {
  wire.rx = {0x12, 0x34, 0xab, 0xcd};
  uint8_t values[4] = {};
  ASSERT_TRUE(bus.read(0x2000, values, sizeof(values)));
  ASSERT_EQ(wire.log.size(), 2u);
  EXPECT_EQ(wire.log[0].address, 0x55);
  EXPECT_EQ(wire.log[0].bytes, (std::vector<uint8_t>{0x20, 0x00}));
  EXPECT_FALSE(wire.log[0].stop);  // Repeated start, no STOP between address and data.
  EXPECT_TRUE(wire.log[1].isRead);
  EXPECT_EQ(wire.log[1].requested, 4u);
  EXPECT_EQ(values[0], 0x12);
  EXPECT_EQ(values[1], 0x34);
  EXPECT_EQ(values[2], 0xab);
  EXPECT_EQ(values[3], 0xcd);
}

TEST_F(WireTransportTest, AddressNackFailsWithoutAReadPhase) {
  wire.endTransmissionResult = 2;
  uint8_t value = 0xee;
  EXPECT_FALSE(bus.read(0x1000, &value, 1));
  EXPECT_EQ(wire.log.size(), 1u);
  EXPECT_EQ(value, 0xee);
}

TEST_F(WireTransportTest, ShortReadFailsAndLeavesTheBufferUntouched) {
  wire.rx = {1, 2, 3, 4};
  wire.shortReadBy = 1;
  uint8_t values[4] = {9, 9, 9, 9};
  EXPECT_FALSE(bus.read(0x2000, values, sizeof(values)));
  EXPECT_EQ(values[0], 9);
}

TEST_F(WireTransportTest, WriteSendsRegisterAndValueWithStop) {
  ASSERT_TRUE(bus.write(0x1003, 4));
  ASSERT_EQ(wire.log.size(), 1u);
  EXPECT_EQ(wire.log[0].bytes, (std::vector<uint8_t>{0x10, 0x03, 0x04}));
  EXPECT_TRUE(wire.log[0].stop);
  wire.endTransmissionResult = 2;
  EXPECT_FALSE(bus.write(0x1003, 4));
}

TEST_F(WireTransportTest, RejectsEmptyOversizedAndNullArguments) {
  uint8_t value;
  EXPECT_FALSE(bus.read(0x1000, &value, 0));
  uint8_t big[33];
  EXPECT_FALSE(bus.read(0x1000, big, sizeof(big)));
  EXPECT_FALSE(bus.read(0x1000, nullptr, 1));
  EXPECT_TRUE(wire.log.empty());
}

TEST(WireTransportUnbound, FailsBeforeBeginInsteadOfDereferencingNull) {
  d7s::BasicWireTransport<FakeWire> bus;
  uint8_t value;
  EXPECT_FALSE(bus.read(0x1000, &value, 1));
  EXPECT_FALSE(bus.write(0x1003, 4));
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
