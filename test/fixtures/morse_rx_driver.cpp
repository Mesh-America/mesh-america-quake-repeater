using RXResult = mesh::MorseRxResult;

static void level(RadioLibWrapper& w, float rssi, uint32_t duration) {
  w.rssi = rssi;
  for (uint32_t elapsed = 0; elapsed < duration; elapsed += 2) {
    advance(2); w.serviceCarrierWave();
  }
}
static void pattern(RadioLibWrapper& w, const char* code, uint32_t unit = 48) {
  for (size_t symbol = 0; code[symbol]; ++symbol) {
    level(w, -80, unit * (code[symbol] == '-' ? 3 : 1));
    if (code[symbol + 1]) level(w, -110, unit);
  }
}
static void receive_e(RadioLibWrapper& w) {
  level(w, -110, 520); pattern(w, "."); level(w, -110, 336);
  assert(!strncmp(w.morseCaptureText(), "E", 1));
}
static void packet_receive_restored(const RadioLibWrapper& w) {
  assert(!w._cw_active && !w._morse_rx_owned && !w._cw_stopping && !w.board.awake);
  assert(!w.chip.carrier && !w.board.before && !w.board.after && !w.chip.starts);
  assert(w.isInRecvMode() && w._rx_ps_armed && w.chip.callback);
  assert(w._profile_refresh_required && w.calibrations);
}

struct FskReceiver : RadioLibWrapper {
  FskReceiver() { reset_ok=true; }
  int16_t prepareMorseReceiver(float frequency_mhz) override {
    _morse_rx_fsk_mode=true;
    chip.fsk=true;
    return RadioLibWrapper::prepareMorseReceiver(frequency_mhz);
  }
};

int main() {
  for (bool gain : {false,true}) {
    RadioLibWrapper w; w._rx_boosted_gain_valid=true; w._cur_rx_boosted_gain=gain;
    assert(w.startMorseRx(902.1f,25,60000)==RXResult::Started);
    assert(w.rx_gain_applies==1 && w.physical_rx_gain==gain && w.rssi_reads==1);
    assert(w.rx_gain_order && w.rx_gain_order<w.chip.last_receive_order && w.chip.raw_rx_starts==1);
    receive_e(w); w.stopMorseRx();
    const auto saved=std::string(w.morseCaptureText());
    const auto generation=w.morseCaptureGeneration(), reads=w.rssi_reads;
    const auto launches=w.chip.raw_rx_starts;
    w.rx_gain_apply_ok=false;
    assert(w.startMorseRx(902.1f,25,60000)==RXResult::Failed);
    assert(w.morseCaptureText()==saved && w.morseCaptureGeneration()==generation && w.rssi_reads==reads);
    assert(w.rx_gain_applies==2 && !w.chip.starts && !w.board.before);
    assert(w.chip.raw_rx_starts==launches);
  }
  // Even partial native FSK preparation needs complete LoRa reconstruction.
  for (bool partial_failure : {false, true}) {
    FskReceiver w;
    w.chip.rx_result=partial_failure ? -705 : 0;
    assert(w.startMorseRx(902.1f,25,60000)==(partial_failure ? RXResult::Failed : RXResult::Started));
    if (partial_failure) {
      assert(w.resets==1 && !w._morse_rx_fsk_mode && !w.chip.fsk);
    } else {
      receive_e(w); const auto saved=std::string(w.morseCaptureText());
      w.reset_ok=false;
      assert(w.stopMorseRx()==RXResult::Failed && w._morse_rx_fsk_mode && w.chip.fsk);
      assert(w.morseRxRecovering() && w.board.awake && w.morseCaptureText()==saved);
      const auto resets=w.resets;
      advance(99); w.serviceCarrierWave(); assert(w.resets==resets);
      w.reset_ok=true;
      advance(1); w.serviceCarrierWave();
      assert(!w._morse_rx_fsk_mode && !w.chip.fsk && w.morseCaptureText()==saved);
    }
    packet_receive_restored(w);
  }
  {
    RadioLibWrapper w;
    const auto primary = w._profiles.primary, secondary = w._profiles.secondary.params;
    assert(w.morseCaptureLength() == 0);
    mesh::MorseRxDiagnostics stats;
    assert(!w.morseRxDiagnostics(stats));
    char empty[2] = {'X', 'Y'};
    assert(w.readMorseCapture(0, empty, sizeof(empty)) == 0 && empty[0] == 0 && empty[1] == 'Y');
    const auto generation = w.morseCaptureGeneration();
    assert(w.startMorseRx(902.1f, 25, 60000) == RXResult::Started);
    assert(w.isMorseRxActive() && !w.isMorseTxActive() && w.isCarrierWaveActive());
    assert(w.morseRxLearning() && w.morseRxFrequency() == 902.1f && w.morseRxRemainingMillis() == 60000);
    assert(w.morseRxBandwidthKHz() == 4.8f && w.morse_bandwidth == 4.8f);
    assert(w._morse_rx && w.chip.raw_rx_starts == 1 && w.board.awake && !w.chip.callback);
    assert(!w._rx_ps_armed && !w._nf_calib_active && !w.isInRecvMode());
    assert(w.morseCaptureGeneration() == generation + 1 && !w.chip.starts && !w.board.before);
    assert(w.startMorseTx(903, 25, "E") == mesh::MorseTxResult::Busy);
    assert(w.setCarrierWave(0, 1000) == mesh::RadioParamApplyResult::BUSY);
    assert(!w.setTxPower(10) && w._cur_dbm == 17);
    level(w, -110, 520); assert(!w.morseRxLearning());
    pattern(w, "..."); level(w, -110, 144);
    pattern(w, "---"); level(w, -110, 144);
    pattern(w, "..."); level(w, -110, 336);
    assert(!strncmp(w.morseCaptureText(), "SOS", 3));
    assert(w.morseRxDiagnostics(stats) && stats.samples > 0 && stats.minimum_dbm == -110 && stats.maximum_dbm == -80);
    const auto captured = std::string(w.morseCaptureText());
    w.clearMorseCapture(); assert(w.morseCaptureText() == captured);
    assert(w.stopMorseRx() == RXResult::Stopped); packet_receive_restored(w);
    assert(w.morseCaptureText() == captured && w._profiles.primary == primary && w._profiles.secondary.params == secondary);
    std::string pages; size_t offset = 0;
    while (offset < w.morseCaptureLength()) {
      char chunk[3]; const auto count = w.readMorseCapture(offset, chunk, sizeof(chunk));
      assert(count); pages += chunk; offset += count;
    }
    assert(pages == captured);
    assert(w.stopMorseRx() == RXResult::Stopped && w.morseCaptureText() == captured);
    const auto stopped_generation = w.morseCaptureGeneration();
    assert(w.startMorseRx(902.1f, 25, 1000) == RXResult::Started);
    assert(w.morseCaptureLength() == 0 && w.morseCaptureGeneration() == stopped_generation + 1);
    assert(w.stopMorseRx() == RXResult::Stopped);
    const auto cleared_generation = w.morseCaptureGeneration();
    w.clearMorseCapture();
    assert(!w._morse_rx && w.morseCaptureLength() == 0 && w.morseCaptureGeneration() == cleared_generation + 1);
  }
  // RX admission fails before receive/PA mutation and never damages a retained capture.
  for (int reason = 0; reason < 12; ++reason) {
    RadioLibWrapper w;
    assert(w.startMorseRx(902.1f, 25, 60000) == RXResult::Started);
    receive_e(w); assert(w.stopMorseRx() == RXResult::Stopped);
    const auto captured = std::string(w.morseCaptureText());
    const auto generation = w.morseCaptureGeneration();
    const auto raw_starts = w.chip.raw_rx_starts, standbys = w.chip.standby_calls;
    float frequency = 902.1f; uint8_t speed = 25; uint32_t duration = 60000;
    RXResult wanted = RXResult::Busy;
    if (reason == 0) w.state = STATE_TX_WAIT;
    if (reason == 1) w.events.record();
    if (reason == 2) w.busy = true;
    if (reason == 3) w.packet = true;
    if (reason == 4) { w.supported = false; wanted = RXResult::Unsupported; }
    if (reason == 5) { frequency = NAN; wanted = RXResult::InvalidFrequency; }
    if (reason == 6) { frequency = 99; wanted = RXResult::InvalidFrequency; }
    if (reason == 7) { speed = 0; wanted = RXResult::InvalidSpeed; }
    if (reason == 8) { speed = uint8_t(mesh::MorseTx::MaxWpm + 1); wanted = RXResult::InvalidSpeed; }
    if (reason == 9) { duration = 999; wanted = RXResult::InvalidDuration; }
    if (reason == 10) { duration = 300001; wanted = RXResult::InvalidDuration; }
    if (reason == 11) { w.receiver_allocation_ok = false; wanted = RXResult::Failed; }
    assert(w.startMorseRx(frequency, speed, duration) == wanted);
    assert(w.morseCaptureText() == captured && w.morseCaptureGeneration() == generation);
    assert(w.chip.raw_rx_starts == raw_starts && w.chip.standby_calls == standbys && !w.board.awake);
  }
  for (uint8_t profile : {0, 1}) {
    RadioLibWrapper w;
    const float frequency = w._profiles.params(profile).freq;
    if (profile) w._profiles.secondary.mode = mesh::RadioProfileMode::Off;
    assert(w.startMorseRx(frequency, 25, 1000) == RXResult::Started);
    assert(!w.chip.starts && !w.board.before && w.isMorseRxActive());
    char reply[160];
    assert(mesh::handleCarrierWaveCommand(&w, "get cw2", reply, sizeof(reply)));
    assert(!strcmp(reply, "> Morse RX owns radio; use get morse"));
    assert(w.stopMorseRx() == RXResult::Stopped); packet_receive_restored(w);
  }
  for (int fault = 0; fault < 7; ++fault) {
    RadioLibWrapper w; w.startMorseRx(902.1f, 25, 60000); receive_e(w); w.stopMorseRx();
    const auto captured = std::string(w.morseCaptureText());
    const auto generation = w.morseCaptureGeneration();
    if (fault == 0) w.board.frequency_ok = false;
    if (fault == 1) w.fail_morse_params = true;
    if (fault == 2) w.chip.rx_result = -705;
    if (fault == 3) w.rssi = NAN;
    if (fault == 4) w.rssi = -181;
    if (fault == 5) w.chip.frequency_result = -705;
    if (fault == 6) w.chip.irq_result = -705;
    assert(w.startMorseRx(902.1f, 25, 60000) == RXResult::Failed);
    assert(w.morseCaptureText() == captured && w.morseCaptureGeneration() == generation);
    assert(!w.chip.starts && !w.board.before && !w.board.after);
    w.board.frequency_ok = true; w.fail_morse_params = false;
    w.chip.rx_result = w.chip.frequency_result = w.chip.irq_result = 0; w.rssi = -110;
    if (w._cw_active) { advance(100); w.serviceCarrierWave(); }
    packet_receive_restored(w);
    assert(w.morseCaptureText() == captured);
  }
  for (int fault : {0, 1, 2, 3}) {
    RadioLibWrapper w; w.startMorseRx(902.1f, 25, 60000); receive_e(w);
    const auto captured = std::string(w.morseCaptureText());
    if (fault == 0) w.fail_tune = true;
    if (fault == 1) w.fail_rx_starts = 2;
    if (fault == 2) w.register_failures = 1;
    if (fault == 3) w.chip.standby_result = w.chip.stop_result = -705;
    assert(w.stopMorseRx() == RXResult::Failed);
    assert(w.isMorseRxActive() && w.morseRxRecovering() && w.board.awake);
    assert(w.morseRxRemainingMillis() == 0 && !w.chip.starts && !w.board.before);
    assert(w.morseCaptureText() == captured);
    w.clearMorseCapture(); assert(w.morseCaptureText() == captured);
    assert(w.startMorseTx(903, 25, "E") == mesh::MorseTxResult::Busy);
    assert(w.startMorseRx(903, 25, 1000) == RXResult::Busy);
    const auto stops = w.chip.stops;
    advance(99); w.serviceCarrierWave(); assert(w.chip.stops == stops);
    w.fail_tune = false; w.fail_rx_starts = 0; w.reset_ok = true;
    w.chip.stop_result = w.chip.standby_result = 0;
    advance(1); w.serviceCarrierWave(); packet_receive_restored(w);
    assert(w.morseCaptureText() == captured);
  }
  for (uint8_t changed : {0, 1, 2}) {
    RadioLibWrapper w; w.startMorseRx(902.1f, 25, 60000); receive_e(w);
    if (changed < 2) ++w._profiles.generation[changed];
    else w._profiles.secondary.params.freq = 902.1f;
    w.serviceCarrierWave();
    if (changed == 2) { assert(w.isMorseRxActive()); w.stopMorseRx(); }
    packet_receive_restored(w);
    assert(!strncmp(w.morseCaptureText(), "E", 1));
  }
  {
    RadioLibWrapper w; g_mock_millis = 0xfffffff0;
    w.startMorseRx(902.1f, 25, 300000); receive_e(w);
    g_mock_millis = uint32_t(0xfffffff0 + 300000);
    w.serviceCarrierWave(); packet_receive_restored(w);
    assert(!strncmp(w.morseCaptureText(), "E", 1));
  }
  {
    RadioLibWrapper w; w.startMorseRx(902.1f, 25, 60000); receive_e(w);
    const auto reads = w.rssi_reads;
    for (int call = 0; call < 100; ++call) w.serviceCarrierWave();
    assert(w.rssi_reads == reads); // repeated foreground calls never busy-spin SPI
    level(w, NAN, 14); assert(w.isMorseRxActive() && w._morse_rx_read_errors == 7);
    mesh::MorseRxDiagnostics stats;
    assert(w.morseRxDiagnostics(stats) && stats.read_errors == 7);
    level(w, -110, 2); assert(w._morse_rx_read_errors == 0);
    level(w, NAN, 16); packet_receive_restored(w);
    assert(!strncmp(w.morseCaptureText(), "E", 1));
  }
}
