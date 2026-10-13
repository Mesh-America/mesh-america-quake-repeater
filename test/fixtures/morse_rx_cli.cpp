int main() {
  TestRadio radio; radio.rx_supported = true;
  char reply[160];
  const auto run = [&](const char* command) {
    memset(reply, '~', sizeof(reply));
    assert(mesh::handleMorseCommand(&radio, command, reply, sizeof(reply)));
    assert(memchr(reply, 0, sizeof(reply)));
    return std::string(reply);
  };
  assert(run("get morse").find("captured=0") != std::string::npos);
  assert(run("morse listen 5").find("OK - Morse RX") == 0);
  assert(radio.rx_active && !radio.active && radio.rx_starts == 1 && !radio.starts);
  assert(radio.frequency == 902.1f && radio.speed == 25 && radio.rx_duration == 300000);
  assert(run("get morse").find("BW 7.81 kHz; 300.000 seconds left") != std::string::npos);
  radio.capture = "CQ TEST SOS";
  const auto saves = mesh::saves;
  assert(run("set morse.freq 903.1").find("busy") != std::string::npos);
  assert(run("set morse.wpm 30").find("busy") != std::string::npos);
  assert(mesh::saves == saves);
  assert(run("morse clear").find("Error: stop Morse") == 0 && radio.capture == "CQ TEST SOS");
  assert(run("morse send E").find("busy") != std::string::npos && !radio.active && radio.rx_active);
  assert(run("morse read") == "> 0000/0011 next=END  truncated=0 CQ TEST SOS");
  assert(run("morse read 3") == "> 0003/0011 next=END  truncated=0 TEST SOS");
  assert(run("morse read 11") == "> 0011/0011 next=END  truncated=0 ");
  assert(run("morse stats") == "> no Morse RX statistics");
  radio.have_rx_diagnostics = true;
  radio.rx_diagnostics.samples = 500;
  radio.rx_diagnostics.noise_dbm = -110;
  radio.rx_diagnostics.minimum_dbm = -112;
  radio.rx_diagnostics.maximum_dbm = -80;
  radio.rx_diagnostics.last_dbm = -109;
  radio.rx_diagnostics.unit_ms = 48;
  radio.rx_diagnostics.read_errors = 2;
  assert(run("morse stats") == "> samples=500; noise=-110.0; min=-112.0; max=-80.0; last=-109.0 dBm; unit=48 ms; gap=0 ms; bad=2");
  const auto saved_stats=radio.rx_diagnostics;
  radio.rx_diagnostics.max_sample_gap_ms=0xffffffff;
  radio.rx_diagnostics.samples=0xffffffff;
  radio.rx_diagnostics.unit_ms=65535;
  radio.rx_diagnostics.read_errors=255;
  char reflected[161]; memset(reflected,'~',sizeof(reflected));
  memcpy(reflected,"AB|",3);
  assert(mesh::handleMorseCommand(&radio,"morse stats",reflected+3,157));
  assert(reflected[160]=='~' && !memcmp(reflected,"AB|",3));
  assert(memchr(reflected+3,0,157) && std::string(reflected+3).find("gap=4294967295 ms")!=std::string::npos);
  radio.rx_diagnostics=saved_stats;
  assert(run("morse stats E").find("Error:") == 0);
  assert(run("morse stop").find("capture retained; receive resumed") != std::string::npos);
  assert(!radio.rx_active && radio.rx_stops == 1 && radio.capture == "CQ TEST SOS");
  assert(run("get morse").find("captured=11") != std::string::npos);
  assert(run("morse read").find("CQ TEST SOS") != std::string::npos);

  // A bounded LoRa CLI reply is a stable page, not a silently truncated message.
  radio.capture.clear();
  for (unsigned i = 0; i < mesh::MorseRx::CaptureCapacity; ++i) radio.capture += char('A' + i % 26);
  radio.capture_truncated = true;
  std::string reconstructed;
  uint32_t offset = 0;
  unsigned pages = 0;
  while (offset < radio.capture.size()) {
    const auto command = std::string("morse read ") + std::to_string(offset);
    const auto page = run(command.c_str());
    unsigned returned = 0, total = 0, truncated = 0;
    char next[5]; int payload = 0;
    assert(sscanf(page.c_str(), "> %u/%u next=%4s truncated=%u %n",
                  &returned, &total, next, &truncated, &payload) == 4);
    assert(returned == offset && total == mesh::MorseRx::CaptureCapacity && truncated == 1 && payload > 0);
    const auto text = page.substr(size_t(payload));
    assert(!text.empty() && page.size() < sizeof(reply));
    reconstructed += text;
    if (!strcmp(next, "END")) offset = total;
    else {
      const auto following = uint32_t(std::strtoul(next, nullptr, 10));
      assert(following == returned + text.size() && following > returned);
      offset = following;
    }
    assert(++pages < 40);
  }
  assert(reconstructed == radio.capture && pages > 1);
  for (const char* argument : {"-1", "4097", "1x", "1.0", "1e1", "4294967296", "99999999999999999999", "1 2"}) {
    const auto command = std::string("morse read ") + argument;
    assert(run(command.c_str()).find("Error:") == 0);
  }
  assert(run("morse read +0").find("> 0000/4096") == 0);
  mesh::usable = false;
  assert(run("morse read").find("> 0000/4096") == 0); // capture remains accessible on settings error
  assert(run("morse stats").find("samples=500") != std::string::npos);
  const auto sessions = radio.rx_starts;
  assert(run("morse listen 1").find("saved Morse settings unavailable") != std::string::npos);
  assert(radio.rx_starts == sessions);
  assert(run("morse clear") == "OK - Morse capture cleared" && radio.capture.empty() && !radio.capture_truncated);
  mesh::usable = true;
  for (const char* duration : {"", "0", "-1", "5.001", "nan", "inf", "1e0", "1junk", "1 2", "0.01", "4294967296", "99999999999999999999"}) {
    const auto starts = radio.rx_starts;
    const auto command = std::string("morse listen ") + duration;
    assert(run(command.c_str()).find("Error:") == 0 && radio.rx_starts == starts);
  }
  for (const char* duration : {"1", "5", ".5", ".0166667", "+2", "\t1\t"}) {
    const auto command = std::string("morse listen ") + duration;
    assert(run(command.c_str()).find("OK - Morse RX") == 0);
    assert(radio.rx_duration >= 1000 && radio.rx_duration <= 300000 && !radio.active);
    run("morse stop");
  }
  for (const char* invalid : {"get morse listen 1", "set morse listen 1", "morse clear 1", "morse stop 1"}) {
    const auto starts = radio.rx_starts, stops = radio.rx_stops;
    assert(run(invalid).find("Error:") == 0 && radio.rx_starts == starts && radio.rx_stops == stops);
  }
  radio.force_rx_result = true;
  for (auto result : {mesh::MorseRxResult::Busy, mesh::MorseRxResult::Unsupported,
      mesh::MorseRxResult::InvalidFrequency, mesh::MorseRxResult::Overlap,
      mesh::MorseRxResult::InvalidSpeed, mesh::MorseRxResult::InvalidDuration,
      mesh::MorseRxResult::Failed}) {
    radio.forced_rx = result;
    assert(run("morse listen 1").find("Error:") == 0);
  }
  radio.force_rx_result = false;
  run("morse listen 1"); radio.capture = "LAST COPY";
  radio.force_rx_result = true; radio.forced_rx = mesh::MorseRxResult::Failed;
  assert(run("morse stop").find("recovery pending; capture retained") != std::string::npos);
  assert(run("get morse").find("packet-radio recovery pending") != std::string::npos);
  assert(run("morse read").find("LAST COPY") != std::string::npos);
  radio.force_rx_result = false; run("morse stop");
  radio.supported = false; // RX-only capability must not require a TX implementation
  assert(run("morse listen 1").find("OK - Morse RX") == 0);
  assert(run("morse send E").find("TX unsupported") != std::string::npos);
  run("morse stop");
  radio.rx_supported = false;
  assert(run("morse listen 1").find("unsupported") != std::string::npos);

  radio.supported = radio.rx_supported = true; radio.capture = std::string(mesh::MorseRx::CaptureCapacity, 'E');
  for (size_t capacity = 1; capacity <= 160; ++capacity) {
    char bounded[162]; memset(bounded, '~', sizeof(bounded));
    assert(mesh::handleMorseCommand(&radio, "morse read 0", bounded, capacity));
    assert(memchr(bounded, 0, capacity) && bounded[capacity] == '~');
  }
}
