int main() {
  static_assert(mesh::MorseRx::SampleIntervalMillis==EXPECTED_SAMPLE_MS,"HIL cadence must not leak into production");
  constexpr uint32_t interval=mesh::MorseRx::SampleIntervalMillis;
  for(uint32_t started : {100U,0xfffffff8U}) {
    RadioLibWrapper w; g_mock_millis=started;
    assert(w.startMorseRx(902.1f,25,60000)==mesh::MorseRxResult::Started);
    assert(w.rssi_reads==1 && w._morse_rx_next_sample==uint32_t(started+interval));
    advance(interval-1); w.serviceCarrierWave(); assert(w.rssi_reads==1);
    advance(1); w.serviceCarrierWave(); assert(w.rssi_reads==2);
    const auto reads=w.rssi_reads;
    for(unsigned call=0;call<100;++call) w.serviceCarrierWave();
    assert(w.rssi_reads==reads); // never catch up/burst merely by foreground calls
    w.rssi_latency=3; advance(interval); w.serviceCarrierWave();
    assert(w.rssi_reads==reads+1 && w._morse_rx_next_sample==uint32_t(g_mock_millis+interval));
    advance(interval-1); w.serviceCarrierWave(); assert(w.rssi_reads==reads+1);
    advance(1); w.serviceCarrierWave(); assert(w.rssi_reads==reads+2);
    w.rssi_latency=0; advance(100); w.serviceCarrierWave();
    const auto stalled=w.rssi_reads;
    for(unsigned call=0;call<100;++call) w.serviceCarrierWave();
    assert(w.rssi_reads==stalled);
    mesh::MorseRxDiagnostics stats;
    assert(w.morseRxDiagnostics(stats) && stats.max_sample_gap_ms>=100);
    assert(w.stopMorseRx()==mesh::MorseRxResult::Stopped && w.isInRecvMode());
  }
}
