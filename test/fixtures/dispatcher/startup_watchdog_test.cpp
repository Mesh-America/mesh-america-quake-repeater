#include <Dispatcher.h>
#include <helpers/StaticPoolPacketManager.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

class TestClock : public mesh::MillisecondClock {
 public:
  unsigned long now = 0;
  unsigned long getMillis() override { return now; }
};

// RadioLib begins in standby and first attempts RX from recvRaw().
class TestRadio : public mesh::Radio {
 public:
  bool in_rx = false;
  bool receive_succeeds = true;
  bool recovery_succeeds = false;
  bool carrier = false;
  unsigned begins = 0;
  unsigned receive_polls = 0;
  std::vector<bool> recoveries;
  std::vector<unsigned> polls_before_recovery;

  void begin() override { ++begins; in_rx = false; }
  int recvRaw(uint8_t*, int) override {
    ++receive_polls;
    if (receive_succeeds) in_rx = true;
    return 0;
  }
  uint32_t getEstAirtimeFor(int) override { return 1; }
  float packetScore(float, int) override { return 0; }
  bool startSendRaw(const uint8_t*, int) override { return false; }
  bool isSendComplete() override { return false; }
  void onSendFinished() override {}
  bool isInRecvMode() const override { return in_rx; }
  bool isCarrierWaveActive() const override { return carrier; }
  bool recoverRadio(bool hard) override {
    recoveries.push_back(hard);
    polls_before_recovery.push_back(receive_polls);
    if (recovery_succeeds) in_rx = true;
    return recovery_succeeds;
  }
};

class TestDispatcher : public mesh::Dispatcher {
 public:
  TestDispatcher(TestRadio& radio, TestClock& clock, StaticPoolPacketManager& manager)
      : Dispatcher(radio, clock, manager) {}
  mesh::DispatcherAction onRecvPacket(mesh::Packet*) override { return ACTION_RELEASE; }
  using Dispatcher::setRadioAvailable;
};

struct Fixture {
  TestClock clock;
  TestRadio radio;
  StaticPoolPacketManager manager{4};
  TestDispatcher dispatcher{radio, clock, manager};

  void beginAt(unsigned long now) { clock.now = now; dispatcher.begin(); }
  void loopAt(unsigned long now) { clock.now = now; dispatcher.loop(); }
  void expectHealthy() {
    assert(dispatcher.getErrFlags() == 0);
    assert(radio.recoveries.empty());
  }
};

static void delayedSetup() {
  Fixture f;
  f.beginAt(1000);
  // Preferences, identity storage and Bluetooth setup run before loop().
  f.loopAt(31000);
  f.expectHealthy();
  assert(f.radio.begins == 1 && f.radio.receive_polls == 1 && f.radio.in_rx);
  f.loopAt(51000);
  f.expectHealthy();
}

static void failedInitialReceive() {
  Fixture f;
  f.radio.receive_succeeds = false;
  f.beginAt(1000);
  f.loopAt(31000);
  f.expectHealthy();
  assert(f.radio.receive_polls == 1);
  f.loopAt(38999);
  f.loopAt(39000);
  f.expectHealthy();
  f.loopAt(39001);
  assert(f.dispatcher.getErrFlags() == ERR_EVENT_STARTRX_TIMEOUT);
  assert(f.radio.recoveries.size() == 1 && !f.radio.recoveries[0]);
  assert(f.radio.polls_before_recovery[0] == 3);
  f.loopAt(39001);
  f.loopAt(47001);
  assert(f.radio.recoveries.size() == 1);
  f.loopAt(47002);
  assert(f.radio.recoveries.size() == 2);
#ifdef RADIO_LIVENESS_SOFT_ONLY
  assert(!f.radio.recoveries[1]);
#else
  assert(f.radio.recoveries[1]);
#endif
}

static void laterReceiveLoss() {
  Fixture f;
  f.beginAt(1000);
  f.loopAt(1000);
  f.loopAt(1001);  // Observe the successful initial RX transition.
  f.radio.in_rx = false;
  f.radio.receive_succeeds = false;
  f.loopAt(31000);
  f.loopAt(39000);
  f.expectHealthy();
  f.radio.recovery_succeeds = true;
  f.loopAt(39001);
  assert(f.radio.recoveries.size() == 1 && !f.radio.recoveries[0]);
  f.loopAt(39002);  // Observe recovery reaching RX, clearing escalation.
  f.radio.in_rx = false;
  f.radio.recovery_succeeds = false;
  f.loopAt(51000);
  f.loopAt(59000);
  assert(f.radio.recoveries.size() == 1);
  f.loopAt(59001);
  assert(f.radio.recoveries.size() == 2 && !f.radio.recoveries[1]);
}

static void delayedReactivation() {
  Fixture f;
  f.radio.receive_succeeds = false;
  f.beginAt(1000);
  f.loopAt(1000);
  f.loopAt(9001);
  assert(f.radio.recoveries.size() == 1);
  f.dispatcher.setRadioAvailable(false);
  const unsigned polls = f.radio.receive_polls;
  f.loopAt(100000);
  assert(f.radio.receive_polls == polls && f.radio.recoveries.size() == 1);
  f.dispatcher.resetStats();
  f.dispatcher.setRadioAvailable(true);
  assert(f.radio.begins == 2);
  f.loopAt(130000);
  assert(f.dispatcher.getErrFlags() == 0 && f.radio.recoveries.size() == 1);
  assert(f.radio.receive_polls == polls + 1);
  f.loopAt(138000);
  assert(f.radio.recoveries.size() == 1);
  f.loopAt(138001);
  assert(f.radio.recoveries.size() == 2 && !f.radio.recoveries[1]);
}

static void repeatedBegin() {
  Fixture f;
  f.radio.receive_succeeds = false;
  f.beginAt(0);
  f.loopAt(0);  // Millis zero must be a valid timer origin.
  f.loopAt(8000);
  f.expectHealthy();
  f.loopAt(8001);
  assert(f.radio.recoveries.size() == 1);
  f.beginAt(100000);
  f.loopAt(130000);
  assert(f.dispatcher.getErrFlags() == 0 && f.radio.recoveries.size() == 1);
  f.loopAt(138000);
  assert(f.radio.recoveries.size() == 1);
  f.loopAt(138001);
  assert(f.radio.recoveries.size() == 2 && !f.radio.recoveries[1]);
}

static void startupWithoutRadio() {
  Fixture f;
  f.dispatcher.setRadioAvailable(false);
  f.beginAt(0);
  f.loopAt(31000);
  f.expectHealthy();
  assert(f.radio.begins == 0 && f.radio.receive_polls == 0);
  f.dispatcher.setRadioAvailable(true);
  f.loopAt(61000);
  f.expectHealthy();
  assert(f.radio.begins == 1 && f.radio.receive_polls == 1 && f.radio.in_rx);
}

static void startupWithCarrier() {
  Fixture f;
  f.radio.carrier = true;
  f.radio.receive_succeeds = false;
  f.beginAt(0);
  f.loopAt(31000);
  f.expectHealthy();
  assert(f.radio.receive_polls == 0);
  f.radio.carrier = false;
  f.loopAt(61000);
  f.expectHealthy();
  assert(f.radio.receive_polls == 1);
  f.loopAt(69000);
  f.expectHealthy();
  f.loopAt(69001);
  assert(f.radio.recoveries.size() == 1 && !f.radio.recoveries[0]);
}

int main(int argc, char** argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "delayed_setup")) delayedSetup();
  else if (!strcmp(argv[1], "failed_initial_receive")) failedInitialReceive();
  else if (!strcmp(argv[1], "later_receive_loss")) laterReceiveLoss();
  else if (!strcmp(argv[1], "delayed_reactivation")) delayedReactivation();
  else if (!strcmp(argv[1], "repeated_begin")) repeatedBegin();
  else if (!strcmp(argv[1], "startup_without_radio")) startupWithoutRadio();
  else if (!strcmp(argv[1], "startup_with_carrier")) startupWithCarrier();
  else assert(false);
  std::printf("%s passed\n", argv[1]);
}
