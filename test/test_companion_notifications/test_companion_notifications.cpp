#include <gtest/gtest.h>
#include <helpers/CompanionNotificationPolicy.h>
#include <vector>
#include <string>

using namespace mesh::notify;
struct OutputSink : Sink {
  bool vibration=false,led=false,gpio=false;
  int8_t screen_state=-1;
  std::string tune;
  uint8_t supported=31;
  uint8_t capabilities() const override { return supported; }
  bool gpioAvailable(uint8_t pin) const override { return pin==22; }
  void pulse(Output o,bool on,int8_t) override {
    if(o==Vibration)vibration=on;else if(o==Led)led=on;else if(o==Gpio)gpio=on;
  }
  void melody(const char* text) override { tune=text?text:""; }
  void screen(int8_t mode) override { screen_state=mode; }
};
struct MemoryStore : Store {
  Settings saved;bool succeeds=true;unsigned writes=0;
  bool save(const Settings& s) override { ++writes;if(!succeeds)return false;saved=s;return true; }
};
class Notifications : public ::testing::Test {
protected:
  OutputSink sink;MemoryStore store;Controller c{sink,store};char reply[160]={};
  std::string cmd(const char* command,uint32_t now=0,bool connected=false) {
    EXPECT_TRUE(c.handle(command,reply,sizeof(reply),now,connected));return reply;
  }
};

TEST(NotificationParsing, MillisecondPulseSequenceAndStrictBounds) {
  Pulse p;ASSERT_TRUE(parsePulse("50,300,40,20,500",p));EXPECT_EQ(910U,p.duration());
  EXPECT_TRUE(p.level(0));EXPECT_TRUE(p.level(49));EXPECT_FALSE(p.level(50));
  EXPECT_FALSE(p.level(349));EXPECT_TRUE(p.level(350));EXPECT_FALSE(p.level(390));
  EXPECT_TRUE(p.level(410));EXPECT_FALSE(p.level(910));
  for(auto text:{"0","-1","50,","50,,20","60001","42949672950","50 20","1,1,1,1,1,1,1,1,1,1,1,1,1"})EXPECT_FALSE(parsePulse(text,p));
  ASSERT_TRUE(parsePulse("off",p));EXPECT_EQ(0,p.count);
}
TEST(NotificationParsing, ValidatesTheActualBuzzerTableAndRtttlSyntax) {
  uint32_t ms;
  ASSERT_TRUE(soundDuration("vip:d=8,o=5,b=120:c,c#,16p,4g.6",ms));EXPECT_GT(ms,0U);
  for(auto text:{"abc","x:d=8,o=3,b=120:c","x:d=8,o=5,b=0:c","x:d=8,o=8,b=120:c",
      "x:d=3,o=5,b=120:c","x:d=8,o=5,b=120:b#7","x:d=8,o=5,b=120:c,",
      "x:d=8,o=5,b=120:c..","x:d=8,o=5,b=120:c8","x:d=8,o=5,b=120:p#",
      "x:d=8,o=5,b=120:c+","x:d=8,o=5,b=120:c, d","x:d=8,o=04,b=120:c",
      "x:d=8,o=5,b=120:c04","x:d=8,o=5,b=120:c007","x:d=08,o=5,b=120:c",
      "x:d=8,o=5,b=120:04c"})EXPECT_FALSE(soundDuration(text,ms))<<text;
}
TEST_F(Notifications, ExecutesExactBoundaryPulsesAndReturnsOutputsOff) {
  EXPECT_EQ("OK",cmd("set notify.led all 50,300,40,20,500"));
  c.loop(0,false);ASSERT_TRUE(c.message(nullptr,nullptr,false,0));EXPECT_TRUE(sink.led);
  c.loop(50,false);EXPECT_FALSE(sink.led);c.loop(350,false);EXPECT_TRUE(sink.led);
  c.loop(390,false);EXPECT_FALSE(sink.led);c.loop(410,false);EXPECT_TRUE(sink.led);
  c.loop(910,false);EXPECT_FALSE(c.active());EXPECT_FALSE(sink.led);
}
TEST_F(Notifications, ContactAndChannelOverrideEachOutputAndConditionIndependently) {
  EXPECT_EQ("OK",cmd("set notify.led all 100"));
  EXPECT_EQ("OK",cmd("set notify.sound all@connected ping:d=8,o=5,b=120:c"));
  const char* key="contact:0101010101010101010101010101010101010101010101010101010101010101";
  std::string command=std::string("set notify.led ")+key+"@connected off";
  EXPECT_EQ("OK",cmd(command.c_str()));
  uint8_t contact[32];memset(contact,1,sizeof(contact));
  c.message(contact,nullptr,true,0);EXPECT_FALSE(sink.led);EXPECT_FALSE(sink.tune.empty());
  c.message(contact,nullptr,false,0);EXPECT_TRUE(sink.led);EXPECT_TRUE(sink.tune.empty());
  cmd("set notify.vibration channel:02020202020202020202020202020202 50,20,50");
  uint8_t channel[16];memset(channel,2,sizeof(channel));
  c.message(nullptr,channel,false,0);EXPECT_TRUE(sink.led);EXPECT_TRUE(sink.vibration);
}
TEST_F(Notifications, DocumentedChannelNineExceptionKeepsOtherMessagesQuiet) {
  // notifications.md: numeric slots are resolved to channel keys by MyMesh.
  // Exercise the same recipe with slot 9's already-resolved key.
  for (const char* command : {
      "set notify.enabled on",
      "set notify.vibration all off",
      "set notify.sound all off",
      "set notify.led all off",
      "set notify.screen all off",
      "set notify.gpio all off",
      "set notify.repeat all 1",
      "set notify.gap all 500",
      "set notify.stop all button",
      "set notify.sound on",
      "set notify.sound channel:09090909090909090909090909090909 ch9:d=8,o=5,b=180:c,e,g"}) {
    EXPECT_EQ("OK", cmd(command)) << command;
  }
  unsigned rules = 0;
  for (const auto& rule : c.settings().rules) if (rule.used) ++rules;
  EXPECT_EQ(2U, rules);
  for (bool connected : {false, true}) {
    for (unsigned slot = 0; slot < 40; ++slot) {
      uint8_t channel[16];memset(channel, slot, sizeof(channel));
      ASSERT_TRUE(c.message(nullptr, channel, connected, 0));
      EXPECT_EQ(slot == 9 ? "ch9:d=8,o=5,b=180:c,e,g" : "", sink.tune);
      EXPECT_FALSE(sink.vibration);EXPECT_FALSE(sink.led);EXPECT_FALSE(sink.gpio);
      EXPECT_EQ(0, sink.screen_state);
      EXPECT_TRUE(c.overridesScreen());
      c.loop(1000, connected);EXPECT_FALSE(c.active());
    }
    uint8_t contact[32];memset(contact, 1, sizeof(contact));
    ASSERT_TRUE(c.message(contact, nullptr, connected, 0));
    EXPECT_TRUE(sink.tune.empty());EXPECT_FALSE(sink.vibration);EXPECT_FALSE(sink.led);
    EXPECT_EQ(0, sink.screen_state);
    c.stop();
  }
  EXPECT_EQ("OK", cmd("set notify.sound off"));
  uint8_t channel[16];memset(channel, 9, sizeof(channel));
  ASSERT_TRUE(c.message(nullptr, channel, false, 0));
  EXPECT_TRUE(sink.tune.empty()); // A rule cannot bypass its master switch.
}
TEST_F(Notifications, ButtonConnectedAndNeverStopPolicies) {
  cmd("set notify.led all 50");cmd("set notify.repeat all forever");
  c.loop(0,false);c.message(nullptr,nullptr,false,0);EXPECT_TRUE(c.button());EXPECT_FALSE(c.active());
  cmd("set notify.stop all connected");c.message(nullptr,nullptr,false,0);
  EXPECT_FALSE(c.button());c.loop(10,true);EXPECT_FALSE(c.active());
  cmd("set notify.stop all never");c.message(nullptr,nullptr,true,20);
  c.loop(30,false);c.loop(40,true);EXPECT_TRUE(c.active());EXPECT_FALSE(c.button());
  EXPECT_EQ("OK - alerts stopped",cmd("notify.stop"));EXPECT_FALSE(c.active());
}
TEST_F(Notifications, ForeverPulsesAcrossMillisRolloverAndSkipsMissedWindows) {
  cmd("set notify.led all 50,300,40,20,500");cmd("set notify.repeat all forever");
  uint32_t start=UINT32_MAX-20;c.message(nullptr,nullptr,false,start);
  c.loop(start+50,false);EXPECT_FALSE(sink.led);
  c.loop(start+350,false);EXPECT_TRUE(sink.led);
  c.loop(start+1410+60,false);EXPECT_FALSE(sink.led);EXPECT_TRUE(c.active());
}
TEST_F(Notifications, GpioUsesTheRepeaterBoardApprovalAndUnsupportedOutputsFail) {
  EXPECT_EQ("Error: GPIO reserved or unavailable; use get notify.gpio.pins",cmd("set notify.gpio all 4:50"));
  EXPECT_EQ("OK",cmd("set notify.gpio all 22:50,300,50"));
  c.message(nullptr,nullptr,false,0);EXPECT_TRUE(sink.gpio);c.loop(50,false);EXPECT_FALSE(sink.gpio);
  sink.supported=Led;EXPECT_EQ("Error: output unsupported on this build",cmd("set notify.vibration all 50"));
  EXPECT_EQ("Error: output unsupported on this build",cmd("set notify.sound on"));
  EXPECT_EQ("> GPIOs: 22",cmd("get notify.gpio.pins"));
}
TEST_F(Notifications, FailedSaveRollsBackRuleMasterAndEnableState) {
  store.succeeds=false;
  EXPECT_EQ("Error: save failed",cmd("set notify.led all 50"));EXPECT_FALSE(c.settings().enabled);
  EXPECT_FALSE(c.settings().rules[0].used);
  EXPECT_EQ("Error: save failed",cmd("set notify.sound off"));EXPECT_EQ(31,c.settings().outputs);
}
TEST_F(Notifications, PatternRestoresNormalDisplayAndDoesNotMutateDisplayPrefs) {
  cmd("set notify.screen all on");c.message(nullptr,nullptr,false,0);EXPECT_EQ(1,sink.screen_state);
  c.loop(1000,false);EXPECT_EQ(-1,sink.screen_state);
  cmd("set notify.screen all off");c.message(nullptr,nullptr,false,0);EXPECT_EQ(0,sink.screen_state);
  c.stop();EXPECT_EQ(-1,sink.screen_state);
}
TEST_F(Notifications, DeleteGetInheritanceAndExplicitTest) {
  cmd("set notify.led all@disconnected 50,300,50");
  EXPECT_EQ("50,300,50",cmd("get notify.led all@disconnected"));
  EXPECT_EQ("OK - alert test started",cmd("notify.test all@disconnected",0,true));EXPECT_TRUE(sink.led);
  EXPECT_EQ("OK",cmd("notify.delete all@disconnected"));EXPECT_FALSE(c.active());
  EXPECT_EQ("inherit",cmd("get notify.led all@disconnected"));
}
TEST_F(Notifications, SettingsValidationRejectsCorruptionAndChangedPinOwnership) {
  cmd("set notify.gpio all 22:50");ASSERT_TRUE(c.validSettings(store.saved));
  store.saved.rules[0].pin=4;EXPECT_FALSE(c.validSettings(store.saved));
  store.saved.rules[0].pin=22;store.saved.rules[0].gpio.count=255;EXPECT_FALSE(c.validSettings(store.saved));
}
TEST_F(Notifications, FiniteRepeatEndsWithoutPlayingAnExtraCycle) {
  cmd("set notify.led all 50");cmd("set notify.repeat all 2");cmd("set notify.gap all 100");
  c.message(nullptr,nullptr,false,0);c.loop(50,false);EXPECT_FALSE(sink.led);EXPECT_TRUE(c.active());
  c.loop(150,false);EXPECT_TRUE(sink.led);c.loop(200,false);EXPECT_FALSE(c.active());EXPECT_FALSE(sink.led);
}

TEST_F(Notifications, DmRequiresAnExplicitFullContactPermissionAndNeverWritesSettings) {
  uint8_t contact[32]={};memset(contact,1,sizeof(contact));
  const char* dm="!notify led=50,300,40,20,500 sound=vip:d=8,o=5,b=180:c,e,g screen=on";
  EXPECT_FALSE(c.remoteMessage(contact,dm,0));
  EXPECT_EQ("OK",cmd("set notify.remote contact:0101010101010101010101010101010101010101010101010101010101010101 on"));
  unsigned writes=store.writes;
  ASSERT_TRUE(c.remoteMessage(contact,dm,0));EXPECT_TRUE(sink.led);EXPECT_EQ(1,sink.screen_state);
  EXPECT_EQ(writes,store.writes);
  uint8_t other[32]={};EXPECT_FALSE(c.remoteMessage(other,dm,0));
  c.stop();EXPECT_FALSE(c.message(contact,nullptr,false,0)); // permission alone does not replace normal alerts
  EXPECT_EQ("OK",cmd("set notify.remote contact:0101010101010101010101010101010101010101010101010101010101010101 off"));
  EXPECT_FALSE(c.remoteMessage(contact,dm,0));
}
TEST_F(Notifications, DmRejectsGpioStopPermissionAndMalformedMessagesAtomically) {
  uint8_t contact[32]={};memset(contact,1,sizeof(contact));
  cmd("set notify.remote contact:0101010101010101010101010101010101010101010101010101010101010101 on");
  for(auto dm:{"!notify led=50 gpio=22:50","!notify led=50 stop=never","!notify remote=on",
      "!notify led=50 led=100","!notify led=50 unknown=foo","!notify sound=unsafe",
      "!notify led=inherit","!notify led=50 ","!notify repeat=forever"}) {
    EXPECT_FALSE(c.remoteMessage(contact,dm,0))<<dm;EXPECT_FALSE(c.active());EXPECT_FALSE(sink.gpio);
  }
  EXPECT_EQ("Error: invalid notification value",cmd("set notify.remote all on"));
  EXPECT_EQ("Error: invalid notification value",cmd("set notify.remote contact:0101010101010101010101010101010101010101010101010101010101010101@connected on"));
}
TEST_F(Notifications, RemoteRepeatingAndLongPatternsHaveAHard15SecondLimitIncludingRollover) {
  uint8_t contact[32]={};memset(contact,1,sizeof(contact));
  cmd("set notify.remote contact:0101010101010101010101010101010101010101010101010101010101010101 on");
  uint32_t started=UINT32_MAX-100;
  ASSERT_TRUE(c.remoteMessage(contact,"!notify led=60000 repeat=forever screen=on",started));
  c.loop(started+14999,false);EXPECT_TRUE(c.active());EXPECT_TRUE(sink.led);
  c.loop(started+15000,false);EXPECT_FALSE(c.active());EXPECT_FALSE(sink.led);EXPECT_EQ(-1,sink.screen_state);
}
TEST_F(Notifications, RoomPermissionUsesTheFullRoomIdentityAndRetryDoesNotExtendTheDeadline) {
  uint8_t room[32];memset(room,2,sizeof(room));
  cmd("set notify.remote room:0202020202020202020202020202020202020202020202020202020202020202 on");
  const char* post="!notify led=60000 repeat=forever";
  ASSERT_TRUE(c.remoteMessage(room,post,0,100));
  ASSERT_TRUE(c.remoteMessage(room,post,14000,100));
  c.loop(15000,false);EXPECT_FALSE(c.active());EXPECT_FALSE(sink.led);
  ASSERT_TRUE(c.remoteMessage(room,post,16000,100));EXPECT_FALSE(c.active());
  uint8_t author[32];memset(author,3,sizeof(author));
  EXPECT_FALSE(c.remoteMessage(author,post,16000,100));
  ASSERT_TRUE(c.remoteMessage(room,post,16000,101));EXPECT_TRUE(c.active());
}

TEST_F(Notifications, IncomingRoomNotificationHonorsRecipientMastersAndButtonDismissal) {
  uint8_t room[32];memset(room,2,sizeof(room));
  cmd("set notify.remote room:0202020202020202020202020202020202020202020202020202020202020202 on");
  cmd("set notify.led off");cmd("set notify.vibration off");cmd("set notify.sound off");
  ASSERT_TRUE(c.remoteMessage(room,"!notify led=1000 vibration=1000 sound=vip:d=8,o=5,b=120:c repeat=forever",0,101));
  EXPECT_FALSE(sink.led);EXPECT_FALSE(sink.vibration);EXPECT_TRUE(sink.tune.empty());
  EXPECT_TRUE(c.button());EXPECT_FALSE(c.active());
  cmd("set notify.enabled off");
  EXPECT_FALSE(c.remoteMessage(room,"!notify led=1000",10,102));
}

int main(int argc,char** argv) { ::testing::InitGoogleTest(&argc,argv);return RUN_ALL_TESTS(); }
