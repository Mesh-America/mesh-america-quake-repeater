using MResult = mesh::MorseTxResult;
using Edge = mesh::MorseTx::Edge;

template <typename Driver> static void complete_message(Driver& w) {
  unsigned edges = 0;
  while (w.isMorseTxActive() && !w._cw_stopping) {
    g_mock_millis = w._morse.nextDeadline();
    assert(w.serviceCarrierWave());
    assert(++edges < 1000);
  }
}

static void fresh_receive(const RadioLibWrapper& w) {
  assert(!w._cw_active && !w._morse_owned && !w._cw_stopping);
  assert(!w.chip.carrier && !w.board.awake && w.chip.callback);
  assert(w.isInRecvMode() && w._rx_ps_armed);
  assert(w._profile_refresh_required && w.calibrations);
}

int main() {
  {
    RadioLibWrapper w;
    const auto primary = w._profiles.primary;
    const auto secondary = w._profiles.secondary.params;
    assert(w.startMorseTx(902.100f, 25, "SOS") == MResult::Started);
    assert(w.isMorseTxActive() && w.isCarrierWaveActive());
    assert(w.chip.carrier && !w.chip.callback && w.board.awake);
    assert(w.morseTxWpm() == 25 && w.morseTxFrequency() == 902.100f);
    assert(w.chip.frequency == 902.100f && w._cur_freq == 909.5f);
    assert(w.morseTxRemainingMillis() == 1296 && w.carrierWaveRemainingMillis() == 1296);
    char reply[160];
    assert(mesh::handleCarrierWaveCommand(&w, "get cw2", reply, sizeof(reply)));
    assert(!strcmp(reply, "> Morse TX owns radio; use get morse"));
    assert(!w.isInRecvMode() && !w._rx_ps_armed && !w._nf_calib_active);
    assert(w._profiles.primary == primary && w._profiles.secondary.params == secondary);
    assert(!w.setTxPower(10)); // power sweeps must not key through Morse gaps
    assert(w.setCarrierWave(0, 100) == mesh::RadioParamApplyResult::BUSY);
    assert(w.startMorseTx(903, 25, "E") == MResult::Busy);
    advance(47); assert(w.serviceCarrierWave() && w.chip.carrier);
    advance(1); assert(w.serviceCarrierWave() && !w.chip.carrier);
    assert(w.isMorseTxActive() && w.board.awake && !w.isInRecvMode());
    assert(w.board.before == 1 && w.board.after == 1 && !w.setTxPower(10));
    complete_message(w);
    fresh_receive(w);
    assert(w.chip.starts == 9 && w.board.before == 9 && w.board.after == 9);
    assert(w._cur_dbm == 17 && w.frequency == 909.5f);
    assert(w._profiles.primary == primary && w._profiles.secondary.params == secondary);
    assert(!w.serviceCarrierWave());
  }
  // Slow/fast bounds, explicit cancellation while keyed and during a gap,
  // rollover and arbitrarily delayed service never synthesize a chirp burst.
  for (uint8_t speed : {1, 25, 60}) {
    RadioLibWrapper w;
    g_mock_millis = 0xfffffff0;
    assert(w.startMorseTx(902.1f, speed, "EE") == MResult::Started);
    const auto first_deadline = w._morse.nextDeadline();
    g_mock_millis = first_deadline;
    w.serviceCarrierWave();
    assert(!w.chip.carrier && w.board.after == 1);
    const auto starts = w.chip.starts;
    for (int i = 0; i < 20; ++i) w.serviceCarrierWave();
    assert(w.chip.starts == starts);
    assert(w.stopMorseTx() == MResult::Stopped);
    fresh_receive(w);
    assert(w.board.before == w.board.after);
    assert(w.startMorseTx(902.1f, speed, "T") == MResult::Started);
    assert(w.stopMorseTx() == MResult::Stopped);
    fresh_receive(w);
  }
  {
    RadioLibWrapper w;
    w.startMorseTx(902.1f, 25, "SOS");
    advance(10000); w.serviceCarrierWave();
    assert(!w.chip.carrier && w.chip.starts == 1 && w.board.after == 1);
    assert(w._morse.nextDeadline() == g_mock_millis + 48);
    w.serviceCarrierWave(); assert(w.chip.starts == 1);
    g_mock_millis = w._morse.hardDeadline(); w.serviceCarrierWave();
    fresh_receive(w);
    assert(w.chip.starts == 1 && w.board.before == w.board.after);
  }
  // Every rejection is before oscillator, receive, external-PA or modem changes.
  for (int reason = 0; reason < 15; ++reason) {
    RadioLibWrapper w;
    float frequency = 902.1f;
    uint8_t speed = 25;
    const char* text = "E";
    MResult wanted = MResult::Busy;
    if (reason == 0) w.state = STATE_TX_WAIT;
    if (reason == 1) w.events.record();
    if (reason == 2) w.busy = true;
    if (reason == 3) w.packet = true;
    if (reason == 4) { w.supported = false; wanted = MResult::Unsupported; }
    if (reason == 5) { frequency = NAN; wanted = MResult::InvalidFrequency; }
    if (reason == 6) { frequency = INFINITY; wanted = MResult::InvalidFrequency; }
    if (reason == 7) { frequency = 99; wanted = MResult::InvalidFrequency; }
    if (reason == 8) { frequency = 1001; wanted = MResult::InvalidFrequency; }
    if (reason == 9) { w._params_valid = false; wanted = MResult::InvalidFrequency; }
    if (reason == 10) { speed = 0; wanted = MResult::InvalidSpeed; }
    if (reason == 11) { speed = uint8_t(mesh::MorseTx::MaxWpm + 1); wanted = MResult::InvalidSpeed; }
    if (reason == 12) { text = "#"; wanted = MResult::InvalidText; }
    if (reason == 13) { w._profiles.primary.freq = 902.1f; wanted = MResult::Overlap; }
    if (reason == 14) { w._profiles.secondary.params.freq = 902.35f; wanted = MResult::Overlap; }
    assert(w.startMorseTx(frequency, speed, text) == wanted);
    assert(!w._cw_active && !w.chip.starts && !w.chip.standby_calls && !w.board.before);
    assert(!w.tunes && !w.board.frequency_prepares);
  }
  {
    RadioLibWrapper w;
    w._profiles.secondary.params.freq = 902.1f;
    w._profiles.secondary.mode = mesh::RadioProfileMode::Off;
    assert(w.startMorseTx(902.1f, 25, "E") == MResult::Overlap);
    assert(!w.chip.starts); // saved radio2 is reserved even while inactive
  }
  for (float frequency : {150.0f, 960.0f}) {
    RadioLibWrapper w;
    w._profiles.primary.bw = 0; w._profiles.primary.sf = 0;
    w._profiles.primary.protocol = mesh::RadioProfileProtocol::Meshtext;
    assert(w.startMorseTx(frequency, 25, "E") == MResult::Started);
    assert(w.stopMorseTx() == MResult::Stopped);
    fresh_receive(w); // unmodulated TX validates band, not cached LoRa SF/BW/protocol
  }
  for (float frequency : {137.0f, 1020.0f}) {
    CustomSX1276Wrapper w;
    assert(w.startMorseTx(frequency, 25, "E") == MResult::Started);
    assert(w.stopMorseTx() == MResult::Stopped); fresh_receive(w);
  }
  for (uint8_t changed_profile : {0, 1}) {
    RadioLibWrapper w; w.startMorseTx(902.1f, 25, "SOS");
    ++w._profiles.generation[changed_profile];
    w.serviceCarrierWave(); fresh_receive(w);
    assert(w.chip.starts == 1);
  }
  {
    RadioLibWrapper w; w.startMorseTx(902.1f, 25, "SOS");
    w._profiles.primary.freq = 902.1f; // board integrations may change tuple directly
    w.serviceCarrierWave(); fresh_receive(w);
    assert(w.chip.starts == 1 && w.frequency == 902.1f);
  }
  {
    RadioLibWrapper w;
    w.chip.tx_latency = 7; w.chip.standby_latency = 8;
    assert(w.startMorseTx(902.1f, 60, "EE") == MResult::Started);
    assert(w._morse.nextDeadline() == g_mock_millis + 20);
    g_mock_millis = w._morse.nextDeadline(); w.serviceCarrierWave();
    assert(!w.chip.carrier && w._morse.nextDeadline() == g_mock_millis + 60);
    g_mock_millis = w._morse.nextDeadline(); w.serviceCarrierWave();
    assert(w.chip.carrier && w._morse.nextDeadline() == g_mock_millis + 20);
    complete_message(w); fresh_receive(w);
    assert(w.chip.starts == 2);
  }
  {
    RadioLibWrapper w; w._active_profile = 1; w.frequency = w._cur_freq = 911.5f;
    w.startMorseTx(902.1f, 25, "E"); complete_message(w); fresh_receive(w);
    assert(w._active_profile == 1 && w.frequency == 911.5f);
  }
  // An unrelated carrier is neither re-keyed nor stopped by Morse operations.
  {
    RadioLibWrapper w;
    w.setCarrierWave(0, 1000);
    assert(w.startMorseTx(902.1f, 25, "E") == MResult::Busy);
    assert(w.stopMorseTx() == MResult::Stopped && w.chip.carrier && w.chip.starts == 1);
    assert(w.setCarrierWave(0, 0) == mesh::RadioParamApplyResult::APPLIED);
  }
  for (int reason = 0; reason < 5; ++reason) {
    RadioLibWrapper w;
    if (reason == 0) w.board.frequency_ok = false;
    if (reason == 1) w.chip.frequency_result = -705;
    if (reason == 2) w.chip.power_result = -705;
    if (reason == 3) w.chip.standby_result = -705;
    if (reason == 4) w.chip.irq_result = -705;
    assert(w.startMorseTx(902.1f, 25, "E") == MResult::Failed);
    assert(!w.chip.starts && !w.board.before);
    if (w._cw_active) assert(w._cw_stopping && w.board.awake);
    w.board.frequency_ok = true;
    w.chip.frequency_result = w.chip.power_result = w.chip.standby_result = w.chip.irq_result = 0;
    if (w._cw_active) { advance(100); w.serviceCarrierWave(); }
    assert(!w._cw_active && !w.board.awake && w.isInRecvMode());
  }
  // Native and FSK chips share fail-closed stop/recovery ownership. Both SPI
  // stop operations may fail, but external transmit is still deasserted.
  {
    RadioLibWrapper w;
    w.startMorseTx(902.1f, 25, "SOS");
    w.chip.stop_result = w.chip.standby_result = -705;
    assert(w.stopMorseTx() == MResult::Failed);
    assert(w._cw_active && w._cw_stopping && w.board.awake && w.board.after == 1);
    assert(!w.setTxPower(10) && w.startMorseTx(903, 25, "E") == MResult::Busy);
    const auto stops = w.chip.stops;
    advance(99); w.serviceCarrierWave(); assert(w.chip.stops == stops);
    w.reset_ok = true;
    advance(1); w.serviceCarrierWave(); fresh_receive(w);
    assert(w.board.after == 1);
  }
  for (int reason : {0, 1, 2}) {
    RadioLibWrapper w;
    w.startMorseTx(902.1f, 25, "EE");
    if (reason == 0) w.chip.standby_result = -705;
    advance(48); w.serviceCarrierWave();
    if (reason == 0) {
      assert(!w._cw_active && !w.board.awake && !w.chip.carrier);
    } else {
      w.chip.start_result = -705;
      if (reason == 2) w.chip.stop_result = w.chip.standby_result = -705;
      advance(144); w.serviceCarrierWave();
      if (reason == 2) assert(w._cw_stopping && w._cw_active && w.board.awake);
      w.chip.start_result = w.chip.stop_result = w.chip.standby_result = 0;
      if (w._cw_active) { advance(100); w.serviceCarrierWave(); }
      fresh_receive(w);
    }
    assert(w.board.before == w.board.after);
  }
  for (int reason : {0, 1}) {
    RadioLibWrapper w; w.startMorseTx(902.1f, 25, "E");
    if (reason == 0) w.fail_tune = true;
    else w.fail_rx_starts = 3;
    assert(w.stopMorseTx() == MResult::Failed);
    assert(w._cw_active && w._cw_stopping && w.board.awake && !w.chip.carrier);
    w.fail_tune = false; w.fail_rx_starts = 0;
    advance(100); w.serviceCarrierWave(); fresh_receive(w);
  }
  {
    RadioLibWrapper w; w.startMorseTx(902.1f, 25, "E");
    w.register_failures = 1;
    assert(w.stopMorseTx() == MResult::Failed);
    assert(w._cw_active && w._cw_stopping && w.board.awake && !w.chip.carrier);
    assert(!w.isInRecvMode());
    advance(100); w.serviceCarrierWave(); fresh_receive(w);
  }
  // SX1276 initializes FSK exactly once for an entire message. PA mapping and
  // LoRa restoration remain production virtual hooks, not fixture equivalents.
  {
    CustomSX1276Wrapper w; w._cur_dbm = 14;
    assert(w.startMorseTx(902.1f, 25, "SOS") == MResult::Started);
    assert(w.chip.fsk && w.chip.fsk_starts == 1 && w.chip.frequency == 902.1f);
    assert(w.chip.deviation == 0 && !w.chip.ook && w.chip.power == 14);
    complete_message(w); fresh_receive(w);
    assert(w.chip.fsk_starts == 1 && w.chip.starts == 9 && !w.chip.fsk);
    assert(w.chip.morse_ramp_calls == 1);
    assert(w.resets == 1 && w.chip.power == 14);
  }
  {
    DacCarrier w; w._cur_dbm = 30;
    assert(w.startMorseTx(902.1f, 25, "SOS") == MResult::Started);
    assert(w.chip.power == 2 && w.gain == 130 && w.chip.carrier);
    complete_message(w); fresh_receive(w);
    assert(w.chip.fsk_starts == 1 && w.chip.starts == 9 && !w.chip.fsk);
    assert(w.chip.power == 2 && w.gain == 130);
  }
  for (int reason : {0, 1, 2, 3}) {
    CustomSX1276Wrapper w;
    if (reason == 0) w.chip.fsk_result = -705;
    if (reason == 1) w.chip.limit_result = -705;
    if (reason == 2) w.chip.power_result = -705;
    if (reason == 3) w.chip.ramp_result = -705;
    assert(w.startMorseTx(902.1f, 25, "SOS") == MResult::Failed);
    assert(!w.chip.starts && !w.chip.carrier && !w.board.before);
    w.chip.power_result = 0;
    if (w._cw_active) { advance(100); w.serviceCarrierWave(); }
    fresh_receive(w);
  }
  {
    CustomSX1276Wrapper w; w.startMorseTx(902.1f, 25, "SOS");
    w.reset_ok = false;
    assert(w.stopMorseTx() == MResult::Failed);
    assert(w._cw_active && w._cw_stopping && w.board.awake && !w.chip.carrier && w.chip.fsk);
    w.reset_ok = true; advance(100); w.serviceCarrierWave(); fresh_receive(w);
    assert(!w.chip.fsk && w.board.before == w.board.after);
  }
}
