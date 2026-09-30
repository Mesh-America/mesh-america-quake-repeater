#include <gtest/gtest.h>

#include <helpers/NRF52VoltageRules.h>

TEST(NRF52VoltageRules, KeepsBoardDefaultsAndRejectsUnsafePairs) {
  EXPECT_TRUE(mesh::power::validThresholdPair(3300, 0, false));
  EXPECT_TRUE(mesh::power::validThresholdPair(3000, 2700, false));
  EXPECT_TRUE(mesh::power::validThresholdPair(0, 0, true));
  EXPECT_FALSE(mesh::power::validThresholdPair(0, 0, false));
  EXPECT_FALSE(mesh::power::validThresholdPair(2499, 0, false));
  EXPECT_FALSE(mesh::power::validThresholdPair(4201, 0, false));
  EXPECT_FALSE(mesh::power::validThresholdPair(3000, 3100, false));
  EXPECT_FALSE(mesh::power::validThresholdPair(0, 2700, true));
  EXPECT_TRUE(mesh::power::validThresholdPair(2000, 2000, false,
                                             mesh::power::MIN_CUSTOM_MV));
  EXPECT_FALSE(mesh::power::validThresholdPair(1999, 0, false,
                                              mesh::power::MIN_CUSTOM_MV));
}

TEST(NRF52VoltageRules, ParsesCliMillivoltsStrictly) {
  uint16_t mv = 1234;
  EXPECT_TRUE(mesh::power::parseVoltageMillivolts("3000", mv, false));
  EXPECT_EQ(mv, 3000);
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("off", mv, false));
  EXPECT_EQ(mv, 3000);
  EXPECT_TRUE(mesh::power::parseVoltageMillivolts("off", mv, true));
  EXPECT_EQ(mv, 0);
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("2499", mv, true));
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("4201", mv, true));
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("3000mV", mv, true));
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("3000 ", mv, true));
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("", mv, true));
  EXPECT_TRUE(mesh::power::parseVoltageMillivolts("2000", mv, false,
                                                 mesh::power::MIN_CUSTOM_MV));
  EXPECT_FALSE(mesh::power::parseVoltageMillivolts("1999", mv, false,
                                                  mesh::power::MIN_CUSTOM_MV));
}

TEST(NRF52VoltageRules, RequiresThreeConsecutiveValidLowReadings) {
  using mesh::power::nextLowVoltageCount;
  EXPECT_EQ(nextLowVoltageCount(0, 2690, 2700, false), 1);
  EXPECT_EQ(nextLowVoltageCount(1, 2650, 2700, false), 2);
  EXPECT_EQ(nextLowVoltageCount(2, 2600, 2700, false), 3);
  EXPECT_EQ(nextLowVoltageCount(2, 2700, 2700, false), 0);
  EXPECT_EQ(nextLowVoltageCount(2, 999, 2700, false), 0);
  EXPECT_EQ(nextLowVoltageCount(2, 2600, 2700, true), 0);
  EXPECT_EQ(nextLowVoltageCount(2, 2600, 0, false), 0);
}

TEST(NRF52VoltageRules, LiFePO4EndpointsAndAdcCalibration) {
  using mesh::power::batteryPercent;
  using mesh::power::calibratedMillivolts;
  EXPECT_EQ(batteryPercent(2700, 2700, 3550), 0);
  EXPECT_EQ(batteryPercent(3125, 2700, 3550), 50);
  EXPECT_EQ(batteryPercent(3550, 2700, 3550), 100);
  EXPECT_EQ(batteryPercent(3700, 2700, 3550), 100);
  EXPECT_EQ(calibratedMillivolts(3000, 1000), 3000);
  EXPECT_EQ(calibratedMillivolts(3000, 1050), 3150);
  EXPECT_EQ(calibratedMillivolts(0, 1500), 0);
}

TEST(NRF52VoltageRules, RemapsCompanionWarningWithBatteryRange) {
  using mesh::power::remapBatteryWarningMillivolts;
  EXPECT_EQ(remapBatteryWarningMillivolts(3500, 3000, 4200,
                                         3000, 4200), 3500);
  EXPECT_EQ(remapBatteryWarningMillivolts(3500, 3000, 4200,
                                         2700, 3550), 3054);
  EXPECT_EQ(remapBatteryWarningMillivolts(3500, 3000, 4200,
                                         2000, 3500), 2625);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
