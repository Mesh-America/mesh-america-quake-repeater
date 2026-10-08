#include <gtest/gtest.h>
#include <string>
#include "helpers/OtaChannel.h"

// The three base URLs are provided as -D macros by the test env (see platformio.ini).
TEST(OtaChannel, ResolvesNativeToBaseMacro) {
  EXPECT_STREQ(ota_resolve_base(OTA_CH_NATIVE), "https://stable.example/mqtt/v");
}
TEST(OtaChannel, ResolvesStable) {
  EXPECT_STREQ(ota_resolve_base(OTA_CH_STABLE), "https://stable.example/mqtt/v");
}
TEST(OtaChannel, ResolvesDev) {
  EXPECT_STREQ(ota_resolve_base(OTA_CH_DEV), "https://dev.example/mqtt/dev/v");
}
TEST(OtaChannel, BasesAreStoredBehindCiTags) {
  EXPECT_STREQ(ota_tagged_native, "ota-base-native:https://stable.example/mqtt/v");
  EXPECT_STREQ(ota_tagged_stable, "ota-base-stable:https://stable.example/mqtt/v");
  EXPECT_STREQ(ota_tagged_dev, "ota-base-dev:https://dev.example/mqtt/dev/v");
}
TEST(OtaChannel, ParseKnownKeywords) {
  uint8_t ch = 99;
  EXPECT_TRUE(ota_parse_channel("prod", &ch));    EXPECT_EQ(ch, OTA_CH_STABLE);
  EXPECT_TRUE(ota_parse_channel("stable", &ch));  EXPECT_EQ(ch, OTA_CH_STABLE);
  EXPECT_TRUE(ota_parse_channel("beta", &ch));    EXPECT_EQ(ch, OTA_CH_DEV);
  EXPECT_TRUE(ota_parse_channel("default", &ch)); EXPECT_EQ(ch, OTA_CH_NATIVE);
  EXPECT_TRUE(ota_parse_channel("dev", &ch));     EXPECT_EQ(ch, OTA_CH_DEV);
}
TEST(OtaChannel, ParseRejectsUnknownAndLeavesOutputUntouched) {
  uint8_t ch = 7;
  EXPECT_FALSE(ota_parse_channel("production", &ch));
  EXPECT_FALSE(ota_parse_channel("Beta", &ch));
  EXPECT_FALSE(ota_parse_channel("", &ch));
  EXPECT_EQ(ch, 7);
}
TEST(OtaChannel, NameLabels) {
  EXPECT_STREQ(ota_channel_name(OTA_CH_NATIVE), "default");
  EXPECT_STREQ(ota_channel_name(OTA_CH_STABLE), "prod");
  EXPECT_STREQ(ota_channel_name(OTA_CH_DEV), "beta");
}
TEST(OtaChannel, NativeChannelNameMatchesBase) {
  EXPECT_STREQ(ota_native_channel_name(), "prod");
}

TEST(OtaCompat, OwnTagParses) {
  OtaCompat own;
  ASSERT_TRUE(ota_compat_parse(ota_compat_tag + sizeof(OTA_COMPAT_TAG) - 1, &own));
  EXPECT_EQ(own.gen, OTA_STATE_GEN);
  EXPECT_EQ(own.caps, OTA_CAP_KEYMIND_PREFS);
}
TEST(OtaCompat, ParsesCapsAndRejectsJunk) {
  OtaCompat c;
  ASSERT_TRUE(ota_compat_parse("12+eth+future", &c));
  EXPECT_EQ(c.gen, 12);
  EXPECT_EQ(c.caps, OTA_CAP_ETH);
  EXPECT_FALSE(ota_compat_parse("", &c));
  EXPECT_FALSE(ota_compat_parse("x1", &c));
  EXPECT_FALSE(ota_compat_parse("2eth", &c));
  EXPECT_FALSE(ota_compat_parse("2+", &c));
  EXPECT_FALSE(ota_compat_parse("2147483648+keymind1", &c));
  ASSERT_TRUE(ota_compat_parse("1+keymind1", &c));
  EXPECT_EQ(c.caps, OTA_CAP_KEYMIND_PREFS);
}
TEST(OtaCompat, FindsCompleteTagOnly) {
  const char img[] = "\xe9junk\0ota-compat:2+eth\0tail";
  const char* v = ota_compat_find((const uint8_t*)img, sizeof(img));
  ASSERT_NE(v, nullptr);
  EXPECT_STREQ(v, "2+eth");
  const char cut[] = "junk ota-compat:2+e";  // value runs past the chunk end
  EXPECT_EQ(ota_compat_find((const uint8_t*)cut, sizeof(cut) - 1), nullptr);
  const char literal_first[] = "ota-compat:\0code\0ota-compat:1\0";  // search literal precedes the tag
  v = ota_compat_find((const uint8_t*)literal_first, sizeof(literal_first));
  ASSERT_NE(v, nullptr);
  EXPECT_STREQ(v, "1");
  const char none[] = "ota-compat";
  EXPECT_EQ(ota_compat_find((const uint8_t*)none, sizeof(none)), nullptr);
}
TEST(OtaCompat, TargetMustKeepStateAndTransports) {
  EXPECT_TRUE(ota_compat_ok({2, 0}, {2, 0}));
  EXPECT_TRUE(ota_compat_ok({1, 0}, {2, OTA_CAP_ETH}));
  EXPECT_FALSE(ota_compat_ok({2, 0}, {1, 0}));                       // cannot read /mqtt.json
  EXPECT_FALSE(ota_compat_ok({2, OTA_CAP_ETH}, {2, 0}));             // drops Ethernet
  EXPECT_TRUE(ota_compat_ok({2, OTA_CAP_ETH}, {3, OTA_CAP_ETH}));
  EXPECT_FALSE(ota_compat_ok({1, OTA_CAP_KEYMIND_PREFS}, {2, 0}));  // upstream JSON generation
  EXPECT_TRUE(ota_compat_ok({1, OTA_CAP_KEYMIND_PREFS}, {1, OTA_CAP_KEYMIND_PREFS}));
}

TEST(OtaCompat, ScannerHandlesEveryTagSplitAndSkipsBareLiteral) {
  const char img[] = "ota-compat:\0junk\0ota-compat:1+keymind1\0tail";
  for (size_t chunk = 1; chunk <= sizeof(img); ++chunk) {
    OtaCompatScanner scanner;
    for (size_t offset = 0; offset < sizeof(img); offset += chunk) {
      const size_t remaining = sizeof(img) - offset;
      scanner.consume((const uint8_t*)img + offset, chunk < remaining ? chunk : remaining);
    }
    OtaCompat value;
    ASSERT_TRUE(scanner.finish(&value)) << chunk;
    EXPECT_EQ(value.gen, 1);
    EXPECT_EQ(value.caps, OTA_CAP_KEYMIND_PREFS);
  }
}

TEST(OtaCompat, ScannerRejectsTruncatedAndSkipsMalformedCandidates) {
  const char truncated[] = "ota-compat:1+keymind1";
  OtaCompatScanner scanner;
  scanner.consume((const uint8_t*)truncated, sizeof(truncated) - 1);
  OtaCompat value;
  EXPECT_FALSE(scanner.finish(&value));

  const char image[] = "ota-compat:2147483648\0ota-compat:1+keymind1\0";
  scanner = OtaCompatScanner();
  scanner.consume((const uint8_t*)image, sizeof(image));
  ASSERT_TRUE(scanner.finish(&value));
  EXPECT_EQ(value.caps, OTA_CAP_KEYMIND_PREFS);
}

TEST(OtaCompat, ScannerRefusesConflictingTagsInAnyOrder) {
  const char compatible[] = "ota-compat:1+keymind1";
  const char upstream[] = "ota-compat:2";
  OtaCompat value;
  for (bool compatible_first : {true, false}) {
    OtaCompatScanner scanner;
    scanner.consume((const uint8_t*)(compatible_first ? compatible : upstream),
                    compatible_first ? sizeof(compatible) : sizeof(upstream));
    scanner.consume((const uint8_t*)(compatible_first ? upstream : compatible),
                    compatible_first ? sizeof(upstream) : sizeof(compatible));
    EXPECT_FALSE(scanner.finish(&value));
  }
  OtaCompatScanner repeated;
  repeated.consume((const uint8_t*)compatible, sizeof(compatible));
  repeated.consume((const uint8_t*)compatible, sizeof(compatible));
  EXPECT_TRUE(repeated.finish(&value));
  const char different_unknown[] = "ota-compat:1+keymind1+future";
  repeated.consume((const uint8_t*)different_unknown, sizeof(different_unknown));
  EXPECT_FALSE(repeated.finish(&value));
}

TEST(OtaCompat, ScannerRefusesOversizedOrIncompleteTagAfterValidTag) {
  const char compatible[] = "ota-compat:1+keymind1";
  OtaCompatScanner scanner;
  scanner.consume((const uint8_t*)compatible, sizeof(compatible));
  const char incomplete[] = "ota-compat:2+future";
  scanner.consume((const uint8_t*)incomplete, sizeof(incomplete) - 1);
  OtaCompat value;
  EXPECT_FALSE(scanner.finish(&value));

  scanner = OtaCompatScanner();
  scanner.consume((const uint8_t*)compatible, sizeof(compatible));
  std::string oversized = "ota-compat:1+keymind1+" + std::string(128, 'a');
  oversized.push_back(0);
  for (char byte : oversized) scanner.consume((const uint8_t*)&byte, 1);
  EXPECT_FALSE(scanner.finish(&value));
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
