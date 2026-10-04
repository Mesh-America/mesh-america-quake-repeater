#include <gtest/gtest.h>
#include <helpers/sensors/SeismicAlert.h>

#include <cmath>
#include <limits>
#include <string>

using namespace seismic;

// ---- Gates -------------------------------------------------------------------------------------

TEST(SeismicGates, TheDefaultPositionIsNotALocation) {
  EXPECT_FALSE(locationIsSet(0.0, 0.0));
  EXPECT_FALSE(locationIsSet(0.0000001, -0.0000001));
}

TEST(SeismicGates, RealPositionsAreSetIncludingOnTheEquatorOrTheMeridian) {
  EXPECT_TRUE(locationIsSet(47.61, -122.33));
  EXPECT_TRUE(locationIsSet(-33.87, 151.21));
  EXPECT_TRUE(locationIsSet(0.0, 10.0));    // on the equator
  EXPECT_TRUE(locationIsSet(51.48, 0.0));   // on the prime meridian
  EXPECT_TRUE(locationIsSet(90.0, 180.0));  // range limits are valid
  EXPECT_TRUE(locationIsSet(-90.0, -180.0));
}

TEST(SeismicGates, NonsensePositionsAreNotSet) {
  const double nan = std::numeric_limits<double>::quiet_NaN();
  const double inf = std::numeric_limits<double>::infinity();
  EXPECT_FALSE(locationIsSet(nan, 10.0));
  EXPECT_FALSE(locationIsSet(10.0, nan));
  EXPECT_FALSE(locationIsSet(inf, 10.0));
  EXPECT_FALSE(locationIsSet(90.1, 10.0));
  EXPECT_FALSE(locationIsSet(10.0, 180.1));
  EXPECT_FALSE(locationIsSet(-91.0, -181.0));
}

// ---- Channel name ------------------------------------------------------------------------------

namespace {
std::string normalized(const char* in, Hashtag* result = nullptr, size_t cap = 24) {
  char out[64] = "unchanged";
  const Hashtag r = normalizeHashtag(in, out, cap);
  if (result) *result = r;
  return r == Hashtag::Ok ? std::string(out) : std::string();
}
}  // namespace

TEST(SeismicHashtag, AcceptsNamesWithOrWithoutTheHashAndLowersTheCase) {
  EXPECT_EQ(normalized("quake-alerts"), "#quake-alerts");
  EXPECT_EQ(normalized("#quake-alerts"), "#quake-alerts");
  EXPECT_EQ(normalized("#Quake-Alerts"), "#quake-alerts");
  EXPECT_EQ(normalized("  #seattle2"), "#seattle2");
  EXPECT_EQ(normalized("9"), "#9");
}

TEST(SeismicHashtag, RefusesEmptyAndMalformedNames) {
  Hashtag r;
  normalized("", &r);
  EXPECT_EQ(r, Hashtag::Empty);
  normalized("#", &r);
  EXPECT_EQ(r, Hashtag::Empty);
  normalized("   ", &r);
  EXPECT_EQ(r, Hashtag::Empty);
  normalized(nullptr, &r);
  EXPECT_EQ(r, Hashtag::Empty);
  for (const char* bad : {"quake alerts", "quake_alerts", "quake.alerts", "quake#alerts", "#qu\xc3\xa4ke", "a/b", "a,b", "quake!"}) {
    normalized(bad, &r);
    EXPECT_EQ(r, Hashtag::BadCharacter) << bad;
  }
}

TEST(SeismicHashtag, ChecksTheOutputBufferAtTheBoundary) {
  Hashtag r;
  // 22 letters + '#' + terminator = 24: fits exactly in a 24-byte field.
  EXPECT_EQ(normalized("abcdefghijklmnopqrstuv", &r), "#abcdefghijklmnopqrstuv");
  EXPECT_EQ(r, Hashtag::Ok);
  normalized("abcdefghijklmnopqrstuvw", &r);  // one more does not
  EXPECT_EQ(r, Hashtag::TooLong);
  normalized("a", &r, 2);  // cap 2 holds only '#' and the terminator
  EXPECT_EQ(r, Hashtag::TooLong);
  normalized("a", &r, 1);
  EXPECT_EQ(r, Hashtag::Empty);
}

// ---- Message -----------------------------------------------------------------------------------

namespace {
const char* const kDisclaimer = "This does not necessarily indicate an earthquake.";
std::string message(double lat, double lon, bool values, unsigned si, unsigned pga, size_t budget = 200, bool test = false) {
  char out[200];
  const size_t n = formatMessage(out, sizeof(out), budget, lat, lon, values, uint16_t(si), uint16_t(pga), test);
  return std::string(out, n);
}
}  // namespace

TEST(SeismicMessage, MatchesTheAgreedWording) {
  EXPECT_EQ(message(47.61, -122.33, true, 433, 1481),
            "Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. "
            "This does not necessarily indicate an earthquake.");
}

TEST(SeismicMessage, RoundsCoordinatesToTwoDecimalsAndNeverPrintsMinusZero) {
  EXPECT_EQ(message(47.6097, -122.3331, false, 0, 0), "Shaking detected near 47.61,-122.33. This does not necessarily indicate an earthquake.");
  EXPECT_EQ(message(-0.004, 0.004, false, 0, 0), "Shaking detected near 0.00,0.00. This does not necessarily indicate an earthquake.");
  EXPECT_EQ(message(-33.875, 151.205, false, 0, 0).substr(0, 41), "Shaking detected near -33.88,151.21. This");
}

TEST(SeismicMessage, ConvertsTheSensorsUnits) {
  // SI raw is tenths of cm/s; PGA raw is tenths of gal, shown as whole gal.
  EXPECT_NE(message(10, 10, true, 5, 4).find("Strength 0.5 cm/s, peak acceleration 0 gal."), std::string::npos);
  EXPECT_NE(message(10, 10, true, 100, 5).find("Strength 10.0 cm/s, peak acceleration 1 gal."), std::string::npos);
  EXPECT_NE(message(10, 10, true, 65535, 65535).find("Strength 6553.5 cm/s, peak acceleration 6554 gal."), std::string::npos);
}

TEST(SeismicMessage, DropsDetailBeforeEverCuttingTheDisclaimer) {
  const std::string full = message(47.61, -122.33, true, 433, 1481);
  const std::string shorter = message(47.61, -122.33, true, 433, 1481, full.size() - 1);
  const std::string shortest = message(47.61, -122.33, true, 433, 1481, shorter.size() - 1);
  EXPECT_NE(shorter.find("peak 148 gal."), std::string::npos);
  EXPECT_EQ(shorter.find("peak acceleration"), std::string::npos);
  EXPECT_EQ(shortest, "Shaking detected near 47.61,-122.33. This does not necessarily indicate an earthquake.");
  for (const std::string& m : {full, shorter, shortest}) EXPECT_NE(m.find(kDisclaimer), std::string::npos);
  EXPECT_LT(shorter.size(), full.size());
  EXPECT_LT(shortest.size(), shorter.size());
}

TEST(SeismicMessage, ReturnsNothingRatherThanAnAmputatedMessage) {
  const std::string shortest = message(47.61, -122.33, false, 0, 0);
  EXPECT_EQ(message(47.61, -122.33, false, 0, 0, shortest.size() - 1), "");
  EXPECT_EQ(message(47.61, -122.33, true, 433, 1481, 10), "");
  char tiny[10];
  EXPECT_EQ(formatMessage(tiny, sizeof(tiny), 200, 1, 1, false, 0, 0), 0u);  // output buffer too small
  EXPECT_EQ(formatMessage(nullptr, 0, 200, 1, 1, false, 0, 0), 0u);
}

TEST(SeismicMessage, TheDisclaimerSurvivesEveryRepeaterNameLength) {
  // The repeater prefixes "<name>: " and a packet leaves 163 characters in all, so the room for the
  // text is 163 - (name + 2). Names run to 31 characters.
  const double coordinates[][2] = {{47.61, -122.33}, {-33.87, -151.21}, {-89.99, -179.99}, {12.34, 5.67}, {0.5, 100.12}};
  const unsigned values[][2] = {{433, 1481}, {65535, 65535}, {0, 0}, {10, 7}};
  for (size_t name = 0; name <= 31; ++name) {
    const size_t budget = 163 - (name + 2);
    for (const auto& c : coordinates) {
      for (const auto& v : values) {
        const std::string m = message(c[0], c[1], true, v[0], v[1], budget);
        ASSERT_FALSE(m.empty()) << "name " << name;
        EXPECT_LE(m.size(), budget);
        EXPECT_NE(m.find(kDisclaimer), std::string::npos);
        EXPECT_EQ(m.compare(m.size() - 49, 49, kDisclaimer), 0);  // and it is at the end, uncut
      }
    }
  }
}

TEST(SeismicMessage, ShowsTheFullWordingForTypicalNames) {
  // The product's own name is 27 characters; the full wording fits with typical coordinates.
  const size_t budget = 163 - (27 + 2);
  const std::string m = message(47.61, -122.33, true, 433, 1481, budget);
  EXPECT_NE(m.find("peak acceleration"), std::string::npos) << m.size() << " vs " << budget;
}

TEST(SeismicMessage, ATestMessageIsMarkedAndCarriesNoValues) {
  const std::string m = message(47.61, -122.33, true, 433, 1481, 200, true);
  EXPECT_EQ(m, "TEST: Shaking detected near 47.61,-122.33. This does not necessarily indicate an earthquake.");
}

// ---- Policy ------------------------------------------------------------------------------------

namespace {
constexpr uint32_t kMin = 60UL * 1000;

struct Rig {
  Policy policy;
  Input in;
  Gates gates;
  uint32_t now = 1000;
  uint32_t jitter = 0;
  Send sent;

  Rig() {
    in.sensorPresent = true;
    gates.channelSet = gates.locationSet = true;
    policy.configure(10 * kMin, 30 * 1000);
  }
  bool step(uint32_t advanceMs = 250) {
    now += advanceMs;
    return policy.update(now, in, gates, jitter, sent);
  }
  // Steps until `ms` have passed and reports whether a send happened in between.
  bool run(uint32_t ms) {
    bool any = false;
    for (uint32_t t = 0; t < ms; t += 250) any |= step();
    return any;
  }
  void shake() { ++in.shakingCount; }
  void processingStarts() { in.processing = true; in.recordValid = false; }
  void processingEnds(uint16_t si, uint16_t pga) {
    in.processing = false;
    in.recordValid = true;
    in.siRaw = si;
    in.pgaRaw = pga;
  }
  // A complete, ordinary event: shaking is reported while the sensor processes it, then the record lands.
  bool fullEvent(uint16_t si = 433, uint16_t pga = 1481) {
    shake();
    processingStarts();
    bool any = run(2000);
    processingEnds(si, pga);
    any |= run(40 * 1000);
    return any;
  }
};
}  // namespace

TEST(SeismicPolicy, DoesNothingWithoutASensor) {
  Rig r;
  r.in.sensorPresent = false;
  r.shake();
  EXPECT_FALSE(r.run(5 * kMin));
  EXPECT_EQ(r.policy.eventsSeen(), 0u);
}

TEST(SeismicPolicy, ReportsFromBeforeItStartedWatchingAreHistory) {
  Rig r;
  r.in.shakingCount = 3;  // reported before the first look
  EXPECT_FALSE(r.run(5 * kMin));
  EXPECT_EQ(r.policy.eventsSeen(), 0u);
  EXPECT_EQ(r.policy.sent(), 0u);
}

TEST(SeismicPolicy, SendsOneMessageWithTheFinalValuesAfterTheSensorFinishes) {
  Rig r;
  ASSERT_FALSE(r.step());  // baseline
  EXPECT_TRUE(r.fullEvent(433, 1481));
  EXPECT_TRUE(r.sent.haveValues);
  EXPECT_EQ(r.sent.siRaw, 433);
  EXPECT_EQ(r.sent.pgaRaw, 1481);
  EXPECT_EQ(r.policy.sent(), 1u);
  EXPECT_EQ(r.policy.phase(), Policy::Phase::Cooldown);
}

TEST(SeismicPolicy, DoesNotSendWhileTheSensorIsStillProcessing) {
  Rig r;
  r.step();
  r.shake();
  r.processingStarts();
  EXPECT_FALSE(r.run(90 * 1000));  // well inside the sensor's two-minute window
  EXPECT_EQ(r.policy.phase(), Policy::Phase::WaitingForRecord);
  EXPECT_EQ(r.policy.sent(), 0u);
}

TEST(SeismicPolicy, WaitsTheRandomDelayBeforeSending) {
  Rig r;
  r.step();
  r.jitter = 7000;
  r.shake();
  r.processingStarts();
  r.run(1000);
  r.processingEnds(100, 200);
  r.step();  // the record is seen here; the delay starts
  EXPECT_EQ(r.policy.phase(), Policy::Phase::Delaying);
  EXPECT_FALSE(r.run(6000));
  EXPECT_TRUE(r.run(1500));
}

TEST(SeismicPolicy, ClampsTheDelayToItsMaximum) {
  Rig r;
  r.step();
  r.jitter = 10 * kMin;  // a bad random value cannot hold the message back for long
  r.shake();
  r.processingStarts();
  r.run(500);
  r.processingEnds(100, 200);
  EXPECT_TRUE(r.run(31 * 1000));
}

TEST(SeismicPolicy, NeverUsesARecordItDidNotSeeBeingWritten) {
  Rig r;
  r.step();
  r.in.recordValid = true;  // the previous event's record, sitting in the sensor
  r.in.siRaw = 999;
  r.in.pgaRaw = 999;
  r.shake();  // reported, but processing is never observed
  EXPECT_FALSE(r.run(Policy::NoProcessingWaitMs - 1000));
  EXPECT_TRUE(r.run(2000 + 31 * 1000));
  EXPECT_FALSE(r.sent.haveValues);  // sends without values rather than stale ones
}

TEST(SeismicPolicy, ReportsWhereAnEventIsAndHowLongIsLeft) {
  Rig r;
  r.step();
  EXPECT_EQ(r.policy.waitRemainingMs(r.now), 0u);  // no event
  r.shake();
  r.processingStarts();
  r.step();
  EXPECT_EQ(r.policy.phase(), Policy::Phase::WaitingForRecord);
  EXPECT_GT(r.policy.waitRemainingMs(r.now), Policy::RecordWaitMs - 2000);
  EXPECT_LE(r.policy.waitRemainingMs(r.now), Policy::RecordWaitMs);
  r.run(Policy::RecordWaitMs - 2000);
  EXPECT_LE(r.policy.waitRemainingMs(r.now), 2000u);
}

TEST(SeismicPolicy, SendsWithoutValuesIfTheSensorNeverFinishes) {
  Rig r;
  r.step();
  r.shake();
  r.processingStarts();
  EXPECT_FALSE(r.run(Policy::RecordWaitMs - 2000));
  EXPECT_TRUE(r.run(2000 + 31 * 1000));
  EXPECT_FALSE(r.sent.haveValues);
}

TEST(SeismicPolicy, AReportThatArrivesWhileAlreadyProcessingStillGetsItsValues) {
  Rig r;
  r.step();
  r.in.processing = true;  // processing was already underway on the poll that saw the flag
  r.shake();
  r.run(1000);
  r.processingEnds(55, 66);
  EXPECT_TRUE(r.run(40 * 1000));
  EXPECT_TRUE(r.sent.haveValues);
  EXPECT_EQ(r.sent.siRaw, 55);
}

TEST(SeismicPolicy, ChannelNotSetMeansNothingIsSent) {
  Rig r;
  r.gates.channelSet = false;
  r.step();
  EXPECT_FALSE(r.fullEvent());
  EXPECT_EQ(r.policy.sent(), 0u);
  EXPECT_EQ(r.policy.suppressed(), 1u);
  EXPECT_EQ(r.policy.lastBlocked(), Block::NoChannel);
}

TEST(SeismicPolicy, LocationNotSetMeansNothingIsSent) {
  Rig r;
  r.gates.locationSet = false;
  r.step();
  EXPECT_FALSE(r.fullEvent());
  EXPECT_EQ(r.policy.sent(), 0u);
  EXPECT_EQ(r.policy.lastBlocked(), Block::NoLocation);
  EXPECT_STREQ(blockText(r.policy.lastBlocked()), "location is not set (set lat and lon)");
}

TEST(SeismicPolicy, AFaultedSensorSendsNothing) {
  Rig r;
  r.in.sensorFaulted = true;
  r.step();
  EXPECT_FALSE(r.fullEvent());
  EXPECT_EQ(r.policy.lastBlocked(), Block::SensorFault);
}

TEST(SeismicPolicy, AMissingSettingIsCheckedWhenSendingSoFixingItBeforehandIsEnough) {
  Rig r;
  r.gates.locationSet = false;
  r.step();
  r.shake();
  r.processingStarts();
  r.run(500);
  r.processingEnds(1, 2);
  r.gates.locationSet = true;  // set during the wait
  EXPECT_TRUE(r.run(40 * 1000));
}

TEST(SeismicPolicy, ASuppressedAlertIsNeverSentLateAndDoesNotStartACooldown) {
  Rig r;
  r.gates.locationSet = false;
  r.step();
  EXPECT_FALSE(r.fullEvent());
  r.gates.locationSet = true;  // fixed afterwards
  EXPECT_FALSE(r.run(5 * kMin));  // the old event is not resurrected
  EXPECT_EQ(r.policy.phase(), Policy::Phase::Idle);
  EXPECT_TRUE(r.fullEvent());  // the next real event is reported straight away: no cooldown was started
}

TEST(SeismicPolicy, IgnoresFurtherReportsDuringTheCooldownThenAlertsAgain) {
  Rig r;
  r.step();
  ASSERT_TRUE(r.fullEvent());
  r.shake();
  r.shake();
  EXPECT_FALSE(r.run(5 * kMin));
  EXPECT_EQ(r.policy.ignoredInCooldown(), 1u);  // reports arriving in the same poll count once
  EXPECT_EQ(r.policy.sent(), 1u);
  EXPECT_GT(r.policy.cooldownRemainingMs(r.now), 0u);
  r.run(6 * kMin);  // the ten minutes are over
  EXPECT_EQ(r.policy.cooldownRemainingMs(r.now), 0u);
  EXPECT_TRUE(r.fullEvent());
  EXPECT_EQ(r.policy.sent(), 2u);
}

TEST(SeismicPolicy, ReportsDuringTheWaitAndTheDelayAreTheSameShaking) {
  Rig r;
  r.step();
  r.shake();
  r.processingStarts();
  r.run(1000);
  r.shake();  // more reports while processing
  r.run(1000);
  r.processingEnds(200, 300);
  r.jitter = 5000;
  r.step();
  r.shake();  // and during the delay
  EXPECT_TRUE(r.run(10 * 1000));
  EXPECT_EQ(r.policy.sent(), 1u);
  EXPECT_FALSE(r.run(5 * kMin));
  EXPECT_EQ(r.policy.sent(), 1u);
}

TEST(SeismicPolicy, WorksAcrossTheMillisecondCounterWrapping) {
  Rig r;
  r.now = 0xffffffffu - 20 * 1000;  // wraps during the event
  r.step();
  EXPECT_TRUE(r.fullEvent(433, 1481));
  EXPECT_EQ(r.sent.siRaw, 433);
  r.run(11 * kMin);
  EXPECT_EQ(r.policy.cooldownRemainingMs(r.now), 0u);
  EXPECT_TRUE(r.fullEvent());
}

TEST(SeismicPolicy, ASensorThatDisappearsAndReturnsStartsFromScratch) {
  Rig r;
  r.step();
  r.in.sensorPresent = false;
  r.run(1000);
  r.in.shakingCount = 7;  // reports accumulated while it was not watched
  r.in.sensorPresent = true;
  EXPECT_FALSE(r.run(kMin));
  EXPECT_EQ(r.policy.eventsSeen(), 0u);  // treated as history
  EXPECT_TRUE(r.fullEvent());            // but a new one is reported
}

TEST(SeismicPolicy, ACooldownSurvivesTheSensorBlinking) {
  Rig r;
  r.step();
  ASSERT_TRUE(r.fullEvent());
  r.in.sensorPresent = false;
  r.step();
  r.in.sensorPresent = true;
  r.step();
  EXPECT_EQ(r.policy.phase(), Policy::Phase::Cooldown);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
