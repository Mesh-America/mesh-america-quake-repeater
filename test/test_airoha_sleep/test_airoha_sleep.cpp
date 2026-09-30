#include <gtest/gtest.h>
#include <Arduino.h>
#include <deque>
#include <string>
#include <vector>

void yield() { ++g_mock_millis; }

#include <helpers/sensors/MicroNMEALocationProvider.h>
#include <helpers/sensors/AirohaSleep.h>

// The production provider overrides this default virtual command sender.
void LocationProvider::sendSentence(const char*) {}

class GpsStream : public Stream {
public:
  std::deque<uint8_t> incoming;
  std::vector<std::string> commands;
  std::string pending_command;
  unsigned reply_on_attempt = 0;
  bool send_ready = true;

  void receive(const char* text) {
    while (*text) incoming.push_back(static_cast<uint8_t>(*text++));
  }
  int available() override { return static_cast<int>(incoming.size()); }
  int read() override {
    if (incoming.empty()) return -1;
    uint8_t c = incoming.front();
    incoming.pop_front();
    return c;
  }
  size_t write(uint8_t c) override {
    pending_command += static_cast<char>(c);
    if (c == '\n') {
      commands.push_back(pending_command);
      pending_command.clear();
      if (reply_on_attempt != 0 && commands.size() == reply_on_attempt) {
        receive("$PAIR001,650,0*38\r\n");
        if (send_ready) receive("$PAIR650,0*25\r\n");
      }
    }
    return 1;
  }
};

TEST(AirohaSleep, RejectsCorruptedAcknowledgment) {
  resetArduinoMock();
  GpsStream uart;
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  uart.receive("$PAIR001,650,0*00\r\n");
  EXPECT_FALSE(gps.waitFor("$PAIR001,650,0", 50));
  EXPECT_EQ(50U, millis());
}

TEST(AirohaSleep, ValidAcknowledgmentAfterCorruptedSentenceIsAccepted) {
  resetArduinoMock();
  GpsStream uart;
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  uart.receive("$PAIR001,650,0*00\r\n$PAIR001,650,0*38\r\n");
  EXPECT_TRUE(gps.waitFor("$PAIR001,650,0", 50));
}

TEST(AirohaSleep, RetriesAndDrainsStaleAcknowledgments) {
  resetArduinoMock();
  GpsStream uart;
  uart.reply_on_attempt = 3;
  uart.receive("$PAIR001,650,0*38\r\n"); // Must not acknowledge a new command.
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  ASSERT_TRUE(airohaEnterSleep(&gps));
  ASSERT_EQ(3U, uart.commands.size());
  for (const auto& command : uart.commands) EXPECT_EQ("$PAIR650,0*25\r\n", command);
  EXPECT_EQ(100U, millis());
}

TEST(AirohaSleep, MissingReceiverIsBoundedToThreeAttempts) {
  resetArduinoMock();
  GpsStream uart;
  uart.receive("$PAIR001,650,0*38\r\n");
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  EXPECT_FALSE(airohaEnterSleep(&gps));
  EXPECT_EQ(3U, uart.commands.size());
  EXPECT_EQ(150U, millis());
}

TEST(AirohaSleep, AcceptedCommandAllowsBoundedReadyGrace) {
  resetArduinoMock();
  GpsStream uart;
  uart.reply_on_attempt = 1;
  uart.send_ready = false;
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  EXPECT_TRUE(airohaEnterSleep(&gps));
  EXPECT_EQ(1U, uart.commands.size());
  EXPECT_EQ(50U, millis());
}

TEST(AirohaSleep, TimeoutWorksAcrossMillisRollover) {
  resetArduinoMock();
  g_mock_millis = UINT32_MAX - 10;
  GpsStream uart;
  MicroNMEALocationProvider gps(uart, nullptr, -1, -1);
  EXPECT_FALSE(gps.waitFor("$PAIR001,650,0", 50));
  EXPECT_EQ(39U, millis());
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
