#include <helpers/MorseCLI.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>

namespace mesh {
static MorseSettings current;
static bool save_ok = true;
static bool usable = true;
static unsigned saves = 0;
const MorseSettings& morseSettings() { return current; }
bool morseSettingsUsable() { return usable; }
bool saveMorseSettings(const MorseSettings& candidate) {
  ++saves;
  if (!save_ok || !validMorseSettings(candidate)) { usable = false; return false; }
  current = candidate;
  usable = true;
  return true;
}
}

struct TestRadio : mesh::Radio {
  bool supported = true, active = false, cw = false, receiving = true;
  bool rx_supported = false, rx_active = false, rx_recovering = false, capture_truncated = false;
  bool force_rx_result = false;
  mesh::MorseRxResult forced_rx = mesh::MorseRxResult::Failed;
  unsigned rx_starts = 0, rx_stops = 0, clears = 0;
  uint32_t rx_duration = 0;
  std::string capture;
  bool have_rx_diagnostics = false;
  mesh::MorseRxDiagnostics rx_diagnostics;
  bool force_result = false;
  mesh::MorseTxResult forced = mesh::MorseTxResult::Failed;
  unsigned starts = 0, stops = 0;
  float frequency = 0;
  uint8_t speed = 0;
  std::string sent;
  uint32_t remaining = 1234;
  bool supportsMorseTx() const override { return supported; }
  bool isMorseTxActive() const override { return active; }
  bool isCarrierWaveActive() const override { return cw || active || rx_active; }
  float morseTxFrequency() const override { return frequency; }
  uint8_t morseTxWpm() const override { return speed; }
  uint32_t morseTxRemainingMillis() const override { return remaining; }
  mesh::MorseTxResult startMorseTx(float freq, uint8_t wpm, const char* text) override {
    ++starts; frequency = freq; speed = wpm; sent = text;
    if (force_result) return forced;
    if (active || cw || rx_active) return mesh::MorseTxResult::Busy;
    const auto result = mesh::MorseTx::validate(text, wpm);
    if (result == mesh::MorseTxResult::Started) active = true;
    return result;
  }
  mesh::MorseTxResult stopMorseTx() override {
    ++stops;
    if (force_result) return forced;
    active = false;
    return mesh::MorseTxResult::Stopped;
  }
  bool supportsMorseRx() const override { return rx_supported; }
  bool isMorseRxActive() const override { return rx_active; }
  bool morseRxRecovering() const override { return rx_recovering; }
  float morseRxFrequency() const override { return frequency; }
  float morseRxBandwidthKHz() const override { return 7.81f; }
  uint32_t morseRxRemainingMillis() const override { return rx_recovering ? 0 : rx_duration; }
  size_t morseCaptureLength() const override { return capture.size(); }
  bool morseCaptureTruncated() const override { return capture_truncated; }
  bool morseRxDiagnostics(mesh::MorseRxDiagnostics& out) const override {
    out = rx_diagnostics; return have_rx_diagnostics;
  }
  const char* morseCaptureText() const override { return capture.c_str(); }
  size_t readMorseCapture(size_t offset, char* out, size_t capacity) const override {
    if (!out || !capacity) return 0;
    if (offset >= capture.size()) { out[0] = 0; return 0; }
    const size_t count = std::min(capture.size() - offset, capacity - 1);
    memcpy(out, capture.data() + offset, count); out[count] = 0; return count;
  }
  void clearMorseCapture() override { ++clears; capture.clear(); capture_truncated = false; }
  mesh::MorseRxResult startMorseRx(float freq, uint8_t wpm, uint32_t duration) override {
    ++rx_starts;
    if (force_rx_result) return forced_rx;
    if (active || cw || rx_active) return mesh::MorseRxResult::Busy;
    const auto valid = mesh::MorseRx::validate(wpm, duration);
    if (valid != mesh::MorseRxResult::Started) return valid;
    frequency = freq; speed = wpm; rx_duration = duration;
    rx_active = true; rx_recovering = false; capture.clear(); capture_truncated = false;
    return mesh::MorseRxResult::Started;
  }
  mesh::MorseRxResult stopMorseRx() override {
    ++rx_stops;
    if (force_rx_result) { rx_recovering = true; return forced_rx; }
    rx_active = rx_recovering = false;
    return mesh::MorseRxResult::Stopped;
  }
  bool isInRecvMode() const override { return receiving && !active && !rx_active; }
  int recvRaw(uint8_t*, int) override { return 0; }
  uint32_t getEstAirtimeFor(int) override { return 1; }
  float packetScore(float, int) override { return 0; }
  bool startSendRaw(const uint8_t*, int) override { return false; }
  bool isSendComplete() override { return false; }
  void onSendFinished() override {}
};

int main() {
  TestRadio radio;
  char reply[180];
  const auto run = [&](const char* command) {
    strcpy(reply, "unchanged");
    assert(mesh::handleMorseCommand(&radio, command, reply, sizeof(reply)));
    return std::string(reply);
  };
  assert(run("get morse") == "> off; 902.100 MHz; 25 WPM; TX only");
  assert(run("get morse.freq") == "> 902.100");
  assert(run("get morse.wpm") == "> 25");
  assert(!radio.starts && !radio.stops && !mesh::saves);
  assert(run("morse send SOS").find("902.100 MHz at 25 WPM") != std::string::npos);
  assert(radio.starts == 1 && radio.active && radio.sent == "SOS");
  assert(radio.frequency == 902.1f && radio.speed == 25);
  assert(run("get morse").find("1.234 seconds left") != std::string::npos);
  radio.remaining = 0;
  assert(run("get morse").find("recovery pending") != std::string::npos);
  assert(run("set morse.wpm 30").find("busy") != std::string::npos);
  assert(run("set morse.freq 903.3").find("busy") != std::string::npos);
  assert(!mesh::saves && mesh::current.wpm == 25);
  assert(run("morse stop").find("receive resumed") != std::string::npos);
  assert(radio.stops == 1 && !radio.active);
  radio.cw = true;
  assert(run("morse stop") == "OK - Morse not running");
  assert(radio.stops == 1 && radio.cw); // never kill an unrelated CW meter test
  assert(run("set morse.wpm 30").find("busy") != std::string::npos);
  radio.cw = false;
  const auto maximum_speed=std::string("set morse.wpm ")+std::to_string(mesh::MorseMaxWpm);
  assert(run(maximum_speed.c_str()).find("OK - morse.wpm")==0);
  for (const char* speed : {"1", "60", "25", "+25", "\t25\t"}) {
    const auto command = std::string("set morse.wpm ") + speed;
    assert(run(command.c_str()).find("OK - morse.wpm") == 0);
  }
  assert(mesh::current.wpm == 25 && radio.starts == 1);
  const auto above_maximum=std::string("set morse.wpm ")+std::to_string(unsigned(mesh::MorseMaxWpm)+1);
  assert(run(above_maximum.c_str()).find("Error:")==0 && mesh::current.wpm==25);
  for (const char* speed : {"", "0", "256", "-1", "25x", "25.0", "2e1",
      "4294967296", "18446744073709551615", "1 2", "nan", "inf", "\n25"}) {
    const auto saves = mesh::saves;
    const auto command = std::string("set morse.wpm ") + speed;
    assert(run(command.c_str()).find("Error:") == 0);
    assert(mesh::saves == saves && mesh::current.wpm == 25 && radio.starts == 1);
  }
  for (const char* frequency : {"100", "1000", "902.100", "902.1004", "+902.1", "\t902.1\t"}) {
    const auto command = std::string("set morse.freq ") + frequency;
    assert(run(command.c_str()).find("OK - morse.freq") == 0);
  }
  assert(mesh::current.frequency_khz == 902100 && radio.starts == 1);
  for (const char* frequency : {"", "99.999", "1000.001", "-902.1", "nan", "inf",
      "902.1MHz", "9.021e2", "4294967296", "18446744073709551615", "902.1 2", "\n902.1"}) {
    const auto saves = mesh::saves;
    const auto command = std::string("set morse.freq ") + frequency;
    assert(run(command.c_str()).find("Error:") == 0);
    assert(mesh::saves == saves && mesh::current.frequency_khz == 902100);
  }
  mesh::save_ok = false;
  assert(run("set morse.wpm 30").find("could not be saved") != std::string::npos);
  assert(run("set morse.freq 903.1").find("could not be saved") != std::string::npos);
  assert(mesh::current.wpm == 25 && mesh::current.frequency_khz == 902100);
  mesh::save_ok = true;
  assert(run("set morse.freq 902.1").find("OK - morse.freq") == 0 && mesh::usable);
  for (const char* invalid : {"get morse x", "get morse send E", "set morse", "set morse send E",
      "morse send", "morse stop E", "morse yes E", "get morse.wpm 25", "get morse.freq 902.1",
      "morse.wpm 25", "morse.freq 902.1"}) {
    const auto starts = radio.starts, stops = radio.stops, saves = mesh::saves;
    assert(run(invalid).find("Error:") == 0);
    assert(radio.starts == starts && radio.stops == stops && mesh::saves == saves);
  }
  for (const char* other : {"hello", "chat SOS", "cw on", "morseX send E", "morse.freqx 902.1", "mt.channel 1"}) {
    strcpy(reply, "unchanged");
    assert(!mesh::handleMorseCommand(&radio, other, reply, sizeof(reply)));
    assert(!strcmp(reply, "unchanged"));
  }
  radio.force_result = true;
  for (auto result : {mesh::MorseTxResult::Busy, mesh::MorseTxResult::Unsupported,
      mesh::MorseTxResult::InvalidFrequency, mesh::MorseTxResult::Overlap,
      mesh::MorseTxResult::InvalidText, mesh::MorseTxResult::InvalidSpeed,
      mesh::MorseTxResult::TooLong, mesh::MorseTxResult::Failed}) {
    radio.forced = result;
    assert(run("morse send E").find("Error:") == 0);
  }
  radio.force_result = false;
  assert(run("morse send #").find("supported Morse ASCII") != std::string::npos);
  assert(run(("morse send " + std::string(81, 'E')).c_str()).find("80 characters") != std::string::npos);
  assert(run("morse send\tsos").find("OK - Morse TX") == 0 && radio.sent == "sos");
  radio.receiving = false;
  assert(run("morse stop").find("receive resumed") == std::string::npos);
  radio.receiving = true;
  {
    mesh::usable = false;
    const auto starts = radio.starts, stops = radio.stops, saves = mesh::saves;
    assert(run("morse send E").find("saved Morse settings unavailable") != std::string::npos);
    assert(run("get morse").find("Error:") == 0);
    assert(run("get morse.freq").find("Error:") == 0);
    assert(run("get morse.wpm").find("Error:") == 0);
    assert(run("set morse.wpm 25").find("verify and save morse.freq") != std::string::npos);
    assert(radio.starts == starts && mesh::saves == saves);
    assert(run("morse stop") == "OK - Morse not running" && radio.stops == stops);
    assert(run("set morse.freq 902.100").find("OK - morse.freq") == 0 && mesh::usable);
    assert(run("morse send E").find("OK - Morse TX") == 0);
    run("morse stop");
  }
  radio.supported = false;
  const auto saves = mesh::saves, starts = radio.starts;
  assert(run("set morse.wpm 25").find("unsupported") != std::string::npos);
  assert(run("morse send E").find("unsupported") != std::string::npos);
  assert(mesh::saves == saves && radio.starts == starts);
  assert(mesh::handleMorseCommand(nullptr, "get morse", reply, sizeof(reply)));
  assert(!strncmp(reply, "Error:", 6));
  assert(!mesh::handleMorseCommand(&radio, nullptr, reply, sizeof(reply)));
  assert(!mesh::handleMorseCommand(&radio, "get morse", nullptr, sizeof(reply)));
  for (size_t capacity = 0; capacity < 30; ++capacity) {
    char small[32]; memset(small, '~', sizeof(small));
    const bool handled = mesh::handleMorseCommand(&radio, "get morse", small, capacity);
    assert(handled == (capacity != 0));
    if (capacity) assert(small[capacity - 1] == 0 || strlen(small) < capacity);
    assert(small[capacity] == '~');
  }
}
