#include <gtest/gtest.h>
#include "helpers/MQTTConnectionHealth.h"

using namespace MQTTConnectionHealth;

TEST(MQTTConnectionHealth, WaitingConfigurationIsNotMarkedAsDown) {
  EXPECT_TRUE(isOutageSlot(true, true, false));
  EXPECT_FALSE(isOutageSlot(true, false, false));
  EXPECT_FALSE(isOutageSlot(false, true, false));
  EXPECT_FALSE(isOutageSlot(true, true, true));
}

TEST(MQTTConnectionHealth, OnlyPendingNeverConnectedAttemptIsAFailure) {
  EXPECT_TRUE(disconnectFailedAttempt(true, false));
  EXPECT_FALSE(disconnectFailedAttempt(false, false)); // deliberate stop/duplicate callback
  EXPECT_FALSE(disconnectFailedAttempt(true, true));   // late live-session bounce
  EXPECT_FALSE(disconnectFailedAttempt(false, true));  // dropped established session
}

TEST(MQTTConnectionHealth, RejectedReconnectPreservesOnlyExistingAttempt) {
  EXPECT_TRUE(clearPendingAfterRejectedRequest(true, false));
  EXPECT_TRUE(clearPendingAfterRejectedRequest(true, true)); // failed start clears stale state
  EXPECT_TRUE(clearPendingAfterRejectedRequest(false, false));
  EXPECT_FALSE(clearPendingAfterRejectedRequest(false, true)); // leave CURRENT state untouched
}

TEST(MQTTConnectionHealth, UnreadyAndDisabledSlotsDoNotCreateFalseOutages) {
  Totals totals;
  addSlot(totals, true, true, true, false, 0, 10000, 2, 3);
  addSlot(totals, true, false, false, true, 1, 10000, 5, 7);
  addSlot(totals, false, true, false, true, 1, 10000, 11, 13);
  EXPECT_EQ(1, totals.up);
  EXPECT_EQ(1, totals.total);
  EXPECT_EQ(0, totals.breakers);
  EXPECT_FALSE(totals.outage_timed);
  EXPECT_EQ(41u, totals.failures); // all history, even disabled slots
}

TEST(MQTTConnectionHealth, DisablingSlotDoesNotReduceFailureHistory) {
  Totals enabled, disabled;
  addSlot(enabled, true, true, false, false, 1000, 9000, 31, 4);
  addSlot(disabled, false, true, false, false, 1000, 9000, 31, 4);
  EXPECT_EQ(enabled.failures, disabled.failures);
  EXPECT_EQ(1, enabled.total);
  EXPECT_EQ(0, disabled.total);
}

TEST(MQTTConnectionHealth, ReadyOutagesChooseWorstAndIgnoreHealthyStaleTimer) {
  Totals totals;
  addSlot(totals, true, true, false, true, 0, 10000, 0, 0); // first attempt still pending
  EXPECT_FALSE(totals.outage_timed);
  addSlot(totals, true, true, false, false, 5000, 10000, 0, 0);
  addSlot(totals, true, true, false, false, 2000, 10000, 0, 0);
  addSlot(totals, true, true, true, false, 1, 10000, 0, 0);
  EXPECT_TRUE(totals.outage_timed);
  EXPECT_EQ(8000u, totals.worst_outage_ms);
  EXPECT_EQ(1, totals.up);
  EXPECT_EQ(4, totals.total);
  EXPECT_EQ(1, totals.breakers);
}

TEST(MQTTConnectionHealth, OutageElapsedIsWrapSafe) {
  Totals totals;
  addSlot(totals, true, true, false, false, UINT32_MAX - 499, 500, 0, 0);
  EXPECT_EQ(1000u, totals.worst_outage_ms);
}

TEST(MQTTConnectionHealth, LifetimeCountersSaturateInsteadOfWrapping) {
  EXPECT_EQ(1u, incrementFailures(0));
  EXPECT_EQ(UINT32_MAX, incrementFailures(UINT32_MAX));
  Totals totals;
  addSlot(totals, false, false, false, false, 0, 0, UINT32_MAX, UINT32_MAX);
  addSlot(totals, false, false, false, false, 0, 0, UINT32_MAX, UINT32_MAX);
  EXPECT_EQ(uint64_t(UINT32_MAX) * 4, totals.failures);
  EXPECT_EQ(INT32_MAX, clampFailureTotal(totals.failures));
  EXPECT_EQ(31, clampFailureTotal(31));
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
