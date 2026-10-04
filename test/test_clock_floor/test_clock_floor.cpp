#include <gtest/gtest.h>

#include <string.h>

#include "helpers/sensors/ClockFloor.h"

using namespace clockfloor;

namespace {
constexpr uint32_t kNow = 1790000000UL;  // 2026-09-21 14:13 UTC
constexpr uint32_t kHour = 3600UL;
constexpr uint32_t kDay = 86400UL;

Record record(uint32_t renewedAt, uint16_t interval = kDefaultIntervalMin, bool enabled = true) {
  Record r;
  r.renewedAt = renewedAt;
  r.intervalMin = interval;
  r.enabled = enabled;
  return r;
}
}  // namespace

// ---- The saved record ------------------------------------------------------------------------------

TEST(ClockFloorRecord, RoundTrips) {
  uint8_t bytes[kRecordSize];
  encode(record(kNow, 90, false), bytes);
  Record back;
  ASSERT_TRUE(decode(bytes, sizeof(bytes), back));
  EXPECT_EQ(back.renewedAt, kNow);
  EXPECT_EQ(back.intervalMin, 90);
  EXPECT_FALSE(back.enabled);
}

TEST(ClockFloorRecord, ADamagedFileIsNeverTrusted) {
  uint8_t good[kRecordSize];
  encode(record(kNow), good);
  Record out;
  EXPECT_FALSE(decode(good, kRecordSize - 1, out));   // too short
  EXPECT_FALSE(decode(good, kRecordSize + 1, out));   // too long
  EXPECT_FALSE(decode(nullptr, kRecordSize, out));
  for (size_t byte = 0; byte < kRecordSize; ++byte) {
    for (int bit = 0; bit < 8; ++bit) {
      uint8_t bad[kRecordSize];
      memcpy(bad, good, sizeof(bad));
      bad[byte] ^= uint8_t(1 << bit);
      // Flipping a reserved byte (10, 11) changes the checksum input too, so everything is caught.
      EXPECT_FALSE(decode(bad, sizeof(bad), out)) << "byte " << byte << " bit " << bit;
    }
  }
}

TEST(ClockFloorRecord, ARecordWithAnInvalidIntervalIsRefused) {
  for (unsigned minutes : {0u, 9u, 1441u, 65535u}) {
    uint8_t bytes[kRecordSize];
    Record r = record(kNow);
    r.intervalMin = uint16_t(minutes);  // bypasses the clamp on purpose
    encode(r, bytes);
    Record out;
    EXPECT_FALSE(decode(bytes, sizeof(bytes), out)) << minutes;
  }
}

TEST(ClockFloorRecord, IntervalIsClamped) {
  EXPECT_EQ(clampInterval(0), kMinIntervalMin);
  EXPECT_EQ(clampInterval(9), kMinIntervalMin);
  EXPECT_EQ(clampInterval(10), 10);
  EXPECT_EQ(clampInterval(360), 360);
  EXPECT_EQ(clampInterval(1440), 1440);
  EXPECT_EQ(clampInterval(100000), kMaxIntervalMin);
}

// ---- At boot ---------------------------------------------------------------------------------------

TEST(ClockFloorRestore, SetsAClockThatFellBackToJustPastWhatWasSent) {
  // A cold start: the clock is back at the firmware's starting date, months behind the saved time.
  const uint32_t restored = restoreTime(kMinTime + 30, record(kNow));
  EXPECT_EQ(restored, kNow + 360 * 60UL + kSlackSec);
}

TEST(ClockFloorRestore, LeavesAClockThatSurvivedTheRestart) {
  // Retained RAM after a soft reset, a real RTC, or GPS: at or past the saved time.
  EXPECT_EQ(restoreTime(kNow, record(kNow)), 0u);
  EXPECT_EQ(restoreTime(kNow + 5 * kHour, record(kNow)), 0u);
  EXPECT_EQ(restoreTime(kNow + 100 * kDay, record(kNow)), 0u);
}

TEST(ClockFloorRestore, LeavesAClockWithinToleranceOfTheSavedTime) {
  EXPECT_EQ(restoreTime(kNow - kToleranceSec, record(kNow)), 0u);
  EXPECT_NE(restoreTime(kNow - kToleranceSec - 1, record(kNow)), 0u);
}

TEST(ClockFloorRestore, DoesNothingWhenOffOrNothingIsSaved) {
  EXPECT_EQ(restoreTime(kMinTime, record(kNow, 360, false)), 0u);
  EXPECT_EQ(restoreTime(kMinTime, record(0)), 0u);
}

TEST(ClockFloorRestore, IgnoresASavedTimeThatCannotBeReal) {
  EXPECT_EQ(restoreTime(kMinTime, record(kMinTime - 1)), 0u);        // before the firmware existed
  EXPECT_EQ(restoreTime(kMinTime, record(kMaxTime + 1)), 0u);        // far in the future
  EXPECT_EQ(restoreTime(kMinTime, record(1000)), 0u);
  EXPECT_NE(restoreTime(kMinTime, record(kMaxTime)), 0u);            // the edge is still accepted
}

TEST(ClockFloorRestore, UsesTheSavedInterval) {
  EXPECT_EQ(restoreTime(kMinTime, record(kNow, 60)), kNow + 3600 + kSlackSec);
  EXPECT_EQ(restoreTime(kMinTime, record(kNow, 1440)), kNow + kDay + kSlackSec);
}

// ---- While running ---------------------------------------------------------------------------------

TEST(ClockFloorKeeper, SavesOnceStraightAwayThenOnlyWhenRenewalIsDue) {
  Keeper keeper;
  keeper.begin(record(0));
  Record out;
  ASSERT_TRUE(keeper.update(kNow, 100, out));
  EXPECT_EQ(out.renewedAt, kNow);
  keeper.saved(out);

  EXPECT_FALSE(keeper.update(kNow + 360 * 60UL - 1, 100 + 360 * 60UL - 1, out));  // just before
  ASSERT_TRUE(keeper.update(kNow + 360 * 60UL, 100 + 360 * 60UL, out));           // exactly due
  EXPECT_EQ(out.renewedAt, kNow + 360 * 60UL);
}

TEST(ClockFloorKeeper, WritesRoughlyFourTimesADayAtTheDefault) {
  Keeper keeper;
  keeper.begin(record(0));
  uint32_t now = kNow, uptime = 1000;
  Record out;
  for (uint32_t second = 0; second < 30 * kDay; ++second, ++now, ++uptime) {
    if (keeper.update(now, uptime, out)) keeper.saved(out);
  }
  EXPECT_GE(keeper.writes(), 4u * 30);
  EXPECT_LE(keeper.writes(), 4u * 30 + 2);  // the first save at the start, nothing more
}

TEST(ClockFloorKeeper, NeverWritesMoreOftenThanTheGapEvenIfAlwaysDue) {
  Keeper keeper;
  keeper.begin(record(kNow, 10));  // renewal due every 10 minutes
  Record out;
  uint32_t writes = 0;
  // The clock races ahead (a bad source), so a write is "due" on every call.
  for (uint32_t i = 0; i < 1000; ++i) {
    if (keeper.update(kNow + i * 100000, 5000 + i, out)) {
      keeper.saved(out);
      ++writes;
    }
  }
  EXPECT_LE(writes, 1000u / (kMinGapSec - 1) + 1);
}

TEST(ClockFloorKeeper, RetriesAFailedWriteOnlyAfterTheGap) {
  Keeper keeper;
  keeper.begin(record(0));
  Record out;
  ASSERT_TRUE(keeper.update(kNow, 100, out));
  keeper.failed();
  EXPECT_FALSE(keeper.update(kNow + 1, 101, out));
  EXPECT_FALSE(keeper.update(kNow + kMinGapSec - 1, 100 + kMinGapSec - 1, out));
  EXPECT_TRUE(keeper.update(kNow + kMinGapSec, 100 + kMinGapSec, out));
  EXPECT_EQ(keeper.failures(), 1u);
  EXPECT_EQ(keeper.writes(), 0u);
}

TEST(ClockFloorKeeper, RenewsRightAfterARestoreSoTheNextRestartStartsFromHere) {
  const Record before = record(kNow);
  const uint32_t restored = restoreTime(kMinTime, before);
  Keeper keeper;
  keeper.begin(before);
  Record out;
  ASSERT_TRUE(keeper.update(restored, 5, out));
  EXPECT_EQ(out.renewedAt, restored);
}

TEST(ClockFloorKeeper, LowersTheSavedTimeWhenTheClockIsSetEarlier) {
  // The saved time is far ahead of a clock someone has since corrected.
  Keeper keeper;
  keeper.begin(record(kNow + 10 * kDay));
  Record out;
  ASSERT_TRUE(keeper.update(kNow, 100, out));
  EXPECT_EQ(out.renewedAt, kNow);  // so a later restart cannot drag the clock into the future
}

TEST(ClockFloorKeeper, LeavesASmallBackwardStepAlone) {
  // Mesh sync nudging the clock back a few minutes does not warrant a write.
  Keeper keeper;
  keeper.begin(record(kNow));
  Record out;
  EXPECT_FALSE(keeper.update(kNow - 20 * 60, 100, out));
}

TEST(ClockFloorKeeper, ASaveRequestedBeforeAPlannedRestartWritesAtOnce) {
  Keeper keeper;
  keeper.begin(record(kNow));
  Record out;
  EXPECT_FALSE(keeper.update(kNow + 1200, 100, out));
  keeper.requestSave();
  ASSERT_TRUE(keeper.update(kNow + 1200, 100, out));  // the saved time is 20 minutes old: worth refreshing
  EXPECT_EQ(out.renewedAt, kNow + 1200);
  keeper.saved(out);
  EXPECT_FALSE(keeper.update(kNow + 1201, 101, out));  // and only once
}

TEST(ClockFloorKeeper, ASaveRequestWhenTheSavedTimeIsFreshWritesNothing) {
  Keeper keeper;
  keeper.begin(record(kNow));
  Record out;
  keeper.requestSave();
  EXPECT_FALSE(keeper.update(kNow + 60, 100, out));  // saved a minute ago: nothing to gain
  // Repeated requests (an admin sending reboot over and over) never become a stream of writes.
  uint32_t writes = 0;
  for (uint32_t i = 0; i < 500; ++i) {
    keeper.requestSave();
    if (keeper.update(kNow + 60 + i, 100 + i, out)) {
      keeper.saved(out);
      ++writes;
    }
  }
  EXPECT_EQ(writes, 0u);
}

TEST(ClockFloorKeeper, ForcedSavesAreStillRateLimited) {
  Keeper keeper;
  keeper.begin(record(kNow));
  Record out;
  keeper.requestSave();
  ASSERT_TRUE(keeper.update(kNow + 3 * kHour, 100, out));  // stale: saved three hours ago
  keeper.saved(out);
  keeper.requestSave();
  EXPECT_FALSE(keeper.update(kNow + 3 * kHour + 20, 120, out));  // fresh again, and inside the gap
  keeper.requestSave();
  EXPECT_TRUE(keeper.update(kNow + 3 * kHour + 2 * kMinGapSec, 100 + 2 * kMinGapSec, out));
}

TEST(ClockFloorKeeper, DoesNothingWhenOffOrWhenTheClockIsNotATime) {
  Keeper off;
  off.begin(record(0, 360, false));
  Record out;
  off.requestSave();
  EXPECT_FALSE(off.update(kNow, 100, out));

  Keeper keeper;
  keeper.begin(record(0));
  EXPECT_FALSE(keeper.update(kMinTime - 1, 100, out));
  EXPECT_FALSE(keeper.update(kMaxTime + 1, 100, out));
}

TEST(ClockFloorKeeper, ChangingTheIntervalChangesWhenRenewalIsDue) {
  Keeper keeper;
  keeper.begin(record(kNow, 360));
  keeper.setIntervalMin(60);
  Record out;
  EXPECT_FALSE(keeper.update(kNow + 3599, 100, out));
  EXPECT_TRUE(keeper.update(kNow + 3600, 100 + 3600, out));
  keeper.setIntervalMin(5);
  EXPECT_EQ(keeper.record().intervalMin, kMinIntervalMin);
}

TEST(ClockFloorKeeper, TheGapSurvivesTheUptimeCounterWrapping) {
  Keeper keeper;
  keeper.begin(record(0));
  Record out;
  const uint32_t nearWrap = 0xFFFFFFFFu - 100;
  ASSERT_TRUE(keeper.update(kNow, nearWrap, out));
  keeper.failed();
  EXPECT_FALSE(keeper.update(kNow + 50, nearWrap + 50, out));              // 50 s later: too soon
  EXPECT_TRUE(keeper.update(kNow + kMinGapSec, nearWrap + kMinGapSec, out));  // wrapped past zero
}

// ---- Date text -------------------------------------------------------------------------------------

TEST(ClockFloorFormat, WritesKnownDatesCorrectly) {
  struct Case {
    uint32_t epoch;
    const char* text;
  } cases[] = {
      {0, "1970-01-01 00:00"},          {951782400, "2000-02-29 00:00"},   {1709164800, "2024-02-29 00:00"},
      {1772323200, "2026-03-01 00:00"}, {1790000000, "2026-09-21 14:13"},  {1790985599, "2026-10-02 23:59"},
  };
  for (const auto& c : cases) {
    char out[32];
    formatUtc(out, sizeof(out), c.epoch);
    EXPECT_STREQ(out, c.text) << c.epoch;
  }
}

// ---- Whole-life simulation -------------------------------------------------------------------------

namespace {
// A repeater with no clock module, living for a while: power is cut at random moments for random
// lengths. Checks the promise: after any restart the clock is never behind anything it sent before.
struct Rng {
  uint32_t s = 12345;
  uint32_t next() {
    s = s * 1664525u + 1013904223u;
    return s >> 8;
  }
};
}  // namespace

TEST(ClockFloorSimulation, NeverGoesBackwardsAcrossRestartsAndNeverStrayFarAhead) {
  for (unsigned intervalMin : {10u, 60u, 360u, 1440u}) {
    Rng rng;
    Record stored;  // the file in flash
    stored.intervalMin = uint16_t(intervalMin);
    uint32_t real = kNow;
    uint32_t clock = kMinTime;  // first ever boot: the built-in date
    uint32_t uptime = 0;
    uint32_t maxSent = 0;       // the highest clock value ever used before a restart
    uint32_t writes = 0;

    auto boot = [&]() {
      Keeper k;
      k.begin(stored);
      return k;
    };
    Keeper keeper = boot();
    const uint32_t lifetime = 60 * kDay;
    const uint32_t startReal = real;
    unsigned restarts = 0;

    while (real - startReal < lifetime) {
      real += 7;  // a loop pass every few seconds is plenty
      clock += 7;
      uptime += 7;
      maxSent = clock > maxSent ? clock : maxSent;
      Record out;
      if (keeper.update(clock, uptime, out)) {
        stored = out;  // the write works
        keeper.saved(out);
        ++writes;
      }
      if (rng.next() % 40000 == 0) {  // an unplanned power loss
        ++restarts;
        real += rng.next() % (3 * kDay);          // dark for up to three days
        clock = kMinTime;                         // the built-in date again
        uptime = 0;
        const uint32_t set = restoreTime(clock, stored);
        if (set != 0) clock = set;
        keeper = boot();
        keeper.begin(stored);
        // The promise: never behind anything sent before the restart.
        ASSERT_GE(clock, maxSent) << "interval " << intervalMin << " restart " << restarts;
        // And not wildly ahead of real time after a short outage: within one interval plus slack.
        // (A long outage leaves it behind real time, which is fine: it is still ahead of what peers saw.)
        if (clock > real) {
          ASSERT_LE(clock - real, intervalMin * 60UL + kSlackSec + kMinGapSec) << "interval " << intervalMin;
        }
        maxSent = clock;
      }
    }
    EXPECT_GT(restarts, 0u) << "the simulation should have exercised restarts";
    // Flash budget: about one write per interval, plus one per restart.
    const double days = double(lifetime) / kDay;
    const double expected = days * 1440.0 / intervalMin + restarts + 2;
    EXPECT_LE(writes, expected * 1.05 + 2) << "interval " << intervalMin;
  }
}

TEST(ClockFloorSimulation, ASoftResetThatKeepsTheClockIsNotJumpedForward) {
  // Retained RAM after a soft reset: the clock is exactly right, so restore must leave it.
  Record stored = record(kNow - 2 * kHour);
  const uint32_t clockAfterSoftReset = kNow;  // survived
  EXPECT_EQ(restoreTime(clockAfterSoftReset, stored), 0u);
}

TEST(ClockFloorSimulation, ATimeSetEarlierIsNotDraggedForwardByTheOldFloor) {
  // Clock was ahead by a week, someone corrected it, and the saved time was lowered by the keeper.
  Keeper keeper;
  keeper.begin(record(kNow + 7 * kDay));
  Record out;
  ASSERT_TRUE(keeper.update(kNow, 100, out));
  keeper.saved(out);
  // Now a power cut: the restart must come back near the corrected time, not a week ahead.
  const uint32_t restored = restoreTime(kMinTime, keeper.record());
  EXPECT_LE(restored, kNow + 360 * 60UL + kSlackSec);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
